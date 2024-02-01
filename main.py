import os
import re
import time
import json
import requests
import threading
import awscrt.exceptions
import sys
import argparse
import yaml
import signal
import logging.config
from uuid import uuid4
from datetime import date
from MQTT.mqtt_callbacks import MqttCallbacks
from awscrt import io as aws_io, mqtt
from awsiot import mqtt_connection_builder, iotshadow
from MQTT.mqtt_device_shadows import DeviceShadows, LockedDeviceState
from Machine.monitoring import MachineStateMonitor


def manage_ctrlc(*args):

    # Reset the shadow
    global ds, exit_main, mqtt_connection

    # Change shadow value to init
    ds.change_shadow_value({"upload_enable": 0})
    exit_main = True

    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()


# Pressing Ctrl+C will call the function `manage_ctrlc` for child process wrap-up
signal.signal(signal.SIGINT, manage_ctrlc)
subscribe_receiving_event = threading.Event()


def get_adapter_ip_from_ssm(topic_ssm_params, ssm_params_payload):

    global subscribe_receiving_event, callbacks
    # Clear the event
    subscribe_receiving_event.clear()

    mqtt_connection.publish(
        topic=topic_ssm_params,
        payload=json.dumps(ssm_params_payload),
        qos=mqtt.QoS.AT_LEAST_ONCE
    )
    # Wait until you receive a message
    while not subscribe_receiving_event.is_set():
        pass

    adapter_ip_ssm = callbacks.params
    return adapter_ip_ssm


def monitor_adapter_ip():

    global config, client_id, machine_name

    # Get the adapter IP address
    # TODO: Improve the way Host is identified
    start_looking = False
    agent_conf_file = config["agent"]["cfg_file"]
    with open(agent_conf_file, "r") as filehandle:
        agent_conf = filehandle.readlines()
        for conf in agent_conf:
            if conf.strip() == machine_name:
                start_looking = True

            if start_looking:
                if "Host" in conf:
                    adapter_ip = conf.strip().split("=")[-1].strip()
                    # Stop looking
                    start_looking = False
                    break

    # Get the IP address from SSM
    topic_ssm_params = config["SSM"]["topic_ssm_params"] + "/" + client_id
    ssm_params_payload = {
        "nodeID": config["SSM"]["nodeID"],
        "execution_type": config["SSM"]["execution_type"],
        "client_id": client_id
    }
    adapter_ip_ssm = get_adapter_ip_from_ssm(topic_ssm_params, ssm_params_payload)
    # Parse the IP
    if adapter_ip_ssm["Status"] == "connected":
        try:
            adapter_ip_ssm = adapter_ip_ssm["ssm_run_command"]["StandardOutputContent"].strip().split()[1]
        except Exception as e:
            logging.error("Cannot get the ip address for the agent from SSM with error message: {}".format(e))
            exit_process(1)
        validate_adapter_ip(adapter_ip, adapter_ip_ssm, agent_conf_file)
    else:
        logger.error("Adapter Offline")
        exit_process(1)


def periodically_check_adapter_ip():
    while True:
        monitor_adapter_ip()
        time.sleep(60 * 60 * 6)


def exit_process(code):
    manage_ctrlc()
    sys.exit(code)


def validate_adapter_ip(adapter_ip, adapter_ip_ssm, agent_cfg_path):

    # Make sure both the arguments are valid ip addresses
    pattern = r'^\d+$'
    for number in adapter_ip.split("."):
        if not bool(re.match(pattern, number)):
            logger.warn("Invalid adapter ip addresses from agent_cfg")
            exit_process(1)
    for number in adapter_ip_ssm.split("."):
        if not bool(re.match(pattern, number)):
            logger.warn("Invalid adapter ip addresses from SSM  manager")
            exit_process(1)

    if adapter_ip != adapter_ip_ssm:
        with open(agent_cfg_path, "r") as filehandle:
            modified_config = ""
            for line in filehandle.readlines():
                if "Host" in line:
                    new_line = line.replace(adapter_ip, adapter_ip_ssm)
                    modified_config += new_line
                else:
                    modified_config += line

        with open(agent_cfg_path, "w") as filehandle:
            filehandle.write(modified_config)
        logger.info(f"IP addresses have been updated from {adapter_ip} to {adapter_ip_ssm}")
        time.sleep(60)
    else:
        logger.info("IP addresses matches")
        return


def initialize_device_shadows(cp):

    # Subscribe to all shadow topics
    # Update
    update_accepted_subscribed_future, _ = shadow_client.subscribe_to_update_named_shadow_accepted(
        request=iotshadow.UpdateNamedShadowSubscriptionRequest(thing_name=cp["client_id"],
                                                               shadow_name=cp["shadow_thing_name"]),
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=ds.on_update_shadow_accepted)
    update_rejected_subscribed_future, _ = shadow_client.subscribe_to_update_named_shadow_rejected(
        request=iotshadow.UpdateNamedShadowSubscriptionRequest(thing_name=cp["client_id"],
                                                               shadow_name=cp["shadow_thing_name"]),
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=ds.on_update_shadow_rejected)
    # Wait for subscriptions to succeed
    update_accepted_subscribed_future.result()
    update_rejected_subscribed_future.result()
    # Get
    get_accepted_subscribed_future, _ = shadow_client.subscribe_to_get_named_shadow_accepted(
        request=iotshadow.GetNamedShadowSubscriptionRequest(thing_name=cp["client_id"],
                                                            shadow_name=cp["shadow_thing_name"]),
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=ds.on_get_shadow_accepted)
    get_rejected_subscribed_future, _ = shadow_client.subscribe_to_get_named_shadow_rejected(
        request=iotshadow.GetNamedShadowSubscriptionRequest(thing_name=cp["client_id"],
                                                            shadow_name=cp["shadow_thing_name"]),
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=ds.on_get_shadow_rejected)
    # Wait for subscriptions to succeed
    get_accepted_subscribed_future.result()
    get_rejected_subscribed_future.result()
    # Delta
    delta_subscribed_future, _ = shadow_client.subscribe_to_named_shadow_delta_updated_events(
        request=iotshadow.NamedShadowDeltaUpdatedSubscriptionRequest(thing_name=cp["client_id"],
                                                                     shadow_name=cp["shadow_thing_name"]),
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=ds.on_shadow_delta_updated)
    # Wait for subscription to succeed
    delta_subscribed_future.result()

    # Get the current shadow state
    with cp["locked_device_state"].lock:
        token = str(uuid4())

        # Publish to get current state
        publish_get_future = shadow_client.publish_get_named_shadow(
            request=iotshadow.GetNamedShadowRequest(thing_name=cp["client_id"], shadow_name=cp["shadow_thing_name"],
                                                    client_token=token),
            qos=mqtt.QoS.AT_LEAST_ONCE
        )
        cp["locked_device_state"].request_tokens.add(token)

    # Ensure the success of publish
    publish_get_future.result()


if __name__ == '__main__':

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-cf", "--config", help="Path to the config file", required=True)
    args = parser.parse_args()
    # Read the configuration
    with open(args.config, 'r') as filehandle:
        config = yaml.load(filehandle, Loader=yaml.Loader)

    # Configure logging
    log_dir = config["logging"]["logging_directory"]
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    d = {
        'version': 1,
        'formatters': {
            'detailed': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        },
        'handlers': {
            'file': {
                'class': 'logging.FileHandler',
                'filename': os.path.join(log_dir, f"{date.today().strftime('%Y%m%d')}.log"),
                'mode': 'a',
                'formatter': 'detailed',
            },
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
            },
        },
        'root': {
            'level': 'INFO',
            'handlers': ['file', 'console']
        },
    }
    logging.config.dictConfig(d)
    logger = logging.getLogger(__name__)

    # Keep track of PIDs
    metadir = os.path.join("/home/minlab/mtconnect-statusUpdate", "metadata")
    if not os.path.exists(metadir):
        os.makedirs(metadir)
    metapath = os.path.join(metadir, "daq_run.meta")
    with open(metapath, "w") as file_handle:
        main_process_pid = os.getpid()
        file_handle.write(str(main_process_pid))
    # Keep track of Process ID
    logger.info(f"PID:{main_process_pid}")

    # Connect to AWS services
    aws_config = config["AWS"]
    endpoint = aws_config["endpoint_url"]
    cert = aws_config["cert"]
    key = aws_config["key"]
    root_ca = aws_config["root_ca"]
    client_id = aws_config["client_id"]
    # Set up AWS logging
    if not os.path.exists(aws_config["logging_directory"]):
        os.makedirs(aws_config["logging_directory"])
    aws_io.init_logging(aws_io.LogLevel.Warn, os.path.join(os.getcwd(), "logs", "aws", "dataLogger_warn.log"))
    # Get the topic for connection
    topic_status_upload = "status/" + client_id
    topic_params_download = "params/" + client_id
    # Get all the callbacks
    set_aws_params = None
    callbacks = MqttCallbacks(set_aws_params, logger, subscribe_receiving_event)

    # Initialize AWS Connection
    try:
        # Establish MQTT Connection
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=endpoint,
                cert_filepath=cert,
                pri_key_filepath=key,
                ca_filepath=root_ca,
                on_connection_interrupted=callbacks.on_connection_interrupted,
                on_connection_resumed=callbacks.on_connection_resumed,
                client_id=client_id,
                clean_session=False,
                keep_alive_secs=30,
                on_connection_success=callbacks.on_connection_success,
                on_connection_failure=callbacks.on_connection_failure,
                on_connection_closed=callbacks.on_connection_closed)
        logger.info("Connecting to {} with client ID '{}'...\n".format(
            endpoint, client_id))
        # Start the connection
        connect_future = mqtt_connection.connect()
        connect_future.result()
        sys.stdout.write("Connection Successful!\n")
        # Start the subscription
        subscribe_future, packet_id = mqtt_connection.subscribe(
            topic=topic_params_download,
            qos=mqtt.QoS.AT_MOST_ONCE,
            callback=callbacks.on_message_received)
        subscribe_result = subscribe_future.result()
        logger.info("Subscribed with {}\n".format(str(subscribe_result['qos'])))

    except awscrt.exceptions.AwsCrtError as e:
        logger.error(f"MQTT Connection to AWS failed with {e}")
        sys.exit(1)

    # Setup Device Shadows
    # Device State of shadow
    locked_device_state = LockedDeviceState()
    connection_params = {
        "mqtt_connection": mqtt_connection,
        "client_id": client_id,
        "shadow_thing_name": aws_config["shadow_name"],
        "locked_device_state": locked_device_state
    }
    # Create Shadow Client
    shadow_client = iotshadow.IotShadowClient(connection_params["mqtt_connection"])
    ds = DeviceShadows(locked_device_state=connection_params["locked_device_state"],
                       client_id=connection_params["client_id"],
                       shadow_thing_name=connection_params["shadow_thing_name"],
                       shadow_client=shadow_client)
    initialize_device_shadows(cp=connection_params)

    # Get the name of machine for status update
    machine_name = config["adapter"]["machine_name"]

    # Monitor the IP address of the adapter
    monitor_adapter_ip()
    # Enable Periodic monitoring of IP address
    monitor_ip_thread = threading.Thread(target=periodically_check_adapter_ip, daemon=True)

    # Initialize Machine Monitoring
    # Collect the params
    devices_xml = config["adapter"]["devices_xml"]
    machine_status = MachineStateMonitor(machine_name=machine_name, devices_xml=devices_xml)

    # Make a http request - To check availability
    url = config["agent"]["url"] + "/" + machine_name + "/current"
    response = requests.get(url)
    machine_status.update_machine_state(response)
    if not machine_status.machine_availability:
        logger.error("FANUC ROBONANO NOT AVAILABLE")
        sys.exit(1)

    # Start sending data every second
    start_upload = False
    start_timer = time.time()
    # Initiate by stopping upload
    ds.change_shadow_value({"upload_enable": 0})
    exit_main = False
    monitor_ip_thread.start()
    while True:

        # Get the shadow state
        with locked_device_state.lock:
            if locked_device_state.states["upload_enable"] == 1:
                start_upload = True
            else:
                start_upload = False

        if start_upload:
            # Make requests to get machine status
            response = requests.get(url)
            machine_status.update_machine_state(response)
            if not machine_status.machine_availability:
                logger.error("FANUC ROBONANO NOT AVAILABLE")
                start_upload = False
                break

            # Construct MQTT Messages
            mqtt_connection.publish(
                topic=topic_status_upload,
                payload=json.dumps(machine_status.machine_params),
                qos=mqtt.QoS.AT_LEAST_ONCE
            )

            # Sleep for a while
            time.sleep(1.0)
            end_timer = time.time()

            # Shutdown data transfer after an hour
            if end_timer - start_timer > 1800:
                start_upload = False
                ds.change_shadow_value({"upload_enable": 0})

        else:
            time.sleep(5.0)
            start_timer = time.time()

        # Break the loop and exit
        if exit_main:
            logger.info(f"Exiting process with PID-{main_process_pid}")
            break


