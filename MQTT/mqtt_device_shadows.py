import os
import threading
import logging
import yaml
from awscrt import mqtt, http
from awsiot import iotshadow, mqtt_connection_builder
from uuid import uuid4


class LockedDeviceState:
    def __init__(self):
        self.lock = threading.Lock()
        self.states = {
            "adapters_connected": None,
            "upload_enable": None,
        }
        self.disconnect_called = False
        self.request_tokens = set()


class DeviceShadows:

    def __init__(self, locked_device_state, client_id, shadow_thing_name, shadow_client):

        # Setup logging
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        self.logger = logging.getLogger("DeviceShadow")

        # Device states
        self.locked_device_state = locked_device_state
        # self.shadow_property = "daq_state"
        self.client_id = client_id
        self.shadow_thing_name = shadow_thing_name
        self.shadow_client = shadow_client
        self.SHADOW_DEFAULT = {}
        for key in self.locked_device_state.states.keys():
            self.SHADOW_DEFAULT[key] = self.locked_device_state.states[key]

    def on_shadow_delta_updated(self, delta):

        if delta.state:
            # Update all the shadow params
            self.change_shadow_value(delta.state)

    def on_get_shadow_accepted(self, response):

        try:
            with self.locked_device_state.lock:
                try:
                    self.locked_device_state.request_tokens.remove(response.client_token)
                except KeyError:
                    self.logger.info("Ignoring update_shadow_accepted message due to unexpected token.")
                    return

                # The first query
                self.logger.info("Finished getting initial shadow state.")
                for key in self.locked_device_state.states.keys():
                    if self.locked_device_state.states[key] is not None:
                        self.logger.info("Ignoring initial query because a delta event has already been received.")
                        return

            if response.state:
                if response.state.delta:
                    self.logger.info("Shadow contains delta value '{}'.".format(response.state.delta))
                    self.change_shadow_value(response.state.delta)
                    return

                if response.state.reported:
                    self.logger.info("Shadow contains reported value '{}'.".format(response.state.reported))
                    self.set_local_value_due_to_initial_query(response.state.reported)
                    return

            return

        except Exception as e:
            self.logger.error(f"Exception occurred at 'on_get_shadow_accepted' with - {e}")

    def on_get_shadow_rejected(self, error):

        try:
            # check that this is a response to a request from this session
            with self.locked_device_state.lock:
                try:
                    self.locked_device_state.request_tokens.remove(error.client_token)
                except KeyError:
                    self.logger.info("Ignoring get_shadow_rejected message due to unexpected token.")
                    return

            if error.code == 404:
                self.logger.info("Thing has no shadow document. Creating with defaults...")
                self.change_shadow_value(self.SHADOW_DEFAULT)
            else:
                self.logger.error("Get request was rejected. code:{} message:'{}'".format(
                    error.code, error.message))

        except Exception as e:
            self.logger.error(f"Exception occurred at 'on_get_shadow_rejected' with - {e}")

    def on_publish_update_shadow(self, future):

        try:
            future.result()
            self.logger.info("Shadow Update request published.")
        except Exception as e:
            self.logger.error(f"Failed to publish update request with - {e}")

    def on_update_shadow_accepted(self, response):

        try:
            # check that this is a response to a request from this session
            with self.locked_device_state.lock:
                try:
                    self.locked_device_state.request_tokens.remove(response.client_token)
                except KeyError:
                    self.logger.info("Shadow Update Request Initiated from Cloud")
                    if response.state.reported is not None:
                        self.set_local_value_due_cloud_change(response.state.reported)
                        return

            if response.state.reported is None:
                self.logger.info("Clearing all shadow states.")
                self.change_shadow_value(self.SHADOW_DEFAULT)

        except Exception as e:
            self.logger.error(f"Exception occurred at 'on_update_shadow_accepted' with - {e}")

    def on_update_shadow_rejected(self, error):

        try:
            # check that this is a response to a request from this session
            with self.locked_device_state.lock:
                try:
                    self.locked_device_state.request_tokens.remove(error.client_token)
                except KeyError:
                    self.logger.info("Ignoring update_shadow_rejected message due to unexpected token.")
                    return

            self.logger.error("Update request was rejected. code:{} message:'{}'".format(
                error.code, error.message))

        except Exception as e:
            self.logger.error(f"Exception occurred at 'on_update_shadow_rejected' with - {e}")

    def set_local_value_due_to_initial_query(self, reported_value):
        with self.locked_device_state.lock:
            for key in reported_value.keys():
                self.locked_device_state.states[key] = reported_value[key]

    def set_local_value_due_cloud_change(self, reported_value):
        for key in reported_value.keys():
            self.locked_device_state.states[key] = reported_value[key]

    def change_shadow_value(self, new_value):

        # If all the values are the same
        changed_values = []
        with self.locked_device_state.lock:
            for key in new_value.keys():
                if self.locked_device_state.states[key] == new_value[key]:
                    continue
                else:
                    changed_values.append(key)
                    if new_value[key] == "none":
                        new_value[key] = None
                    self.locked_device_state.states[key] = new_value[key]

            if len(changed_values) == 0:
                self.logger.info(f"Shadow values are unchanged")
                return

        self.logger.info("Shadow values that were changed - {}".format(changed_values))

        # Use unique messages on accepted or rejected topics
        token = str(uuid4())
        if new_value["upload_enable"] == "clear_shadow":
            tmp_state = iotshadow.ShadowState(
                reported=None,
                desired=None,
                reported_is_nullable=True,
                desired_is_nullable=True)
            request = iotshadow.UpdateNamedShadowRequest(
                thing_name=self.client_id,
                shadow_name=self.shadow_thing_name,
                state=tmp_state,
                client_token=token
            )

        else:
            request = iotshadow.UpdateNamedShadowRequest(
                thing_name=self.client_id,
                shadow_name=self.shadow_thing_name,
                state=iotshadow.ShadowState(
                    reported=self.locked_device_state.states,
                    desired=self.locked_device_state.states
                ),
                client_token=token,
            )

        future = self.shadow_client.publish_update_named_shadow(request, mqtt.QoS.AT_LEAST_ONCE)
        self.locked_device_state.request_tokens.add(token)
        future.add_done_callback(self.on_publish_update_shadow)
