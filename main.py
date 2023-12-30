import os
import time
import json
import requests
import awscrt.exceptions
import sys
import argparse
import yaml
import logging.config
from uuid import uuid4
from datetime import date
from MQTT.mqtt_callbacks import MqttCallbacks
from awscrt import io as aws_io, mqtt
from awsiot import mqtt_connection_builder, iotshadow
from MQTT.mqtt_device_shadows import DeviceShadows, LockedDeviceState
from Machine.monitoring import MachineStateMonitor


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
    callbacks = MqttCallbacks(set_aws_params, logger)

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

    # Initialize Machine Monitoring
    # Collect the params
    devices_xml = config["adapter"]["devices_xml"]
    machine_status = MachineStateMonitor(machine_name=config["adapter"]["machine_name"], devices_xml=devices_xml)

    # Make a http request - To check availability
    url = config["agent"]["url"]
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
            print(end_timer - start_timer)

            # Shutdown data transfer after an hour
            if end_timer - start_timer > 1800:
                print("New Stopping")
                start_upload = False
                ds.change_shadow_value({"upload_enable": 0})

        else:
            time.sleep(5.0)
            start_timer = time.time()


