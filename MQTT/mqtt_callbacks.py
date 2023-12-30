import sys
import json
from awsiot import mqtt


class MqttCallbacks:
    def __init__(self, params, logger):
        self.params = params
        self.logger = logger

    def on_connection_interrupted(self, connection, error, **kwargs):
        self.logger.warn("Connection interrupted. Error: {}".format(error))

    def on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        self.logger.info("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

        if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
            self.logger.info("Session did not persist. Resubscribing to existing topics...")
            resubscribe_future, _ = connection.resubscribe_existing_topics()

            # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
            # evaluate result with a callback instead.
            resubscribe_future.add_done_callback(self.on_resubscribe_complete)

    @staticmethod
    def on_resubscribe_complete(resubscribe_future):
        resubscribe_results = resubscribe_future.result()

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("Server rejected resubscribe to topic: {}".format(topic))

    def on_message_received(self, topic, payload, dup, qos, retain, **kwargs):
        print("Received message from topic '{}': {}".format(topic, payload))

        # Change the datatype
        payload = json.loads(payload)

        # Put the payload in queue
        self.params = payload

    def on_connection_success(self, connection, callback_data):
        assert isinstance(callback_data, mqtt.OnConnectionSuccessData)
        self.logger.info("Connection Successful with return code: {} session present: {}".format(callback_data.return_code,
                                                                                      callback_data.session_present))

    # Callback when a connection attempt fails
    def on_connection_failure(self, connection, callback_data):
        assert isinstance(callback_data, mqtt.OnConnectionFailureData)
        self.logger.warn("Connection failed with error code: {}".format(callback_data.error))

    # Callback when a connection has been disconnected or shutdown successfully
    def on_connection_closed(self, connection, callback_data):
        self.logger.info("Connection closed")
