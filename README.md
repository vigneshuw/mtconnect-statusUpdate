# MTConnect Status Update

We are using MTConnect to update the status of an Ultra-precision CNC machine - FANUC ROBONANO $\alpha$-0*i*B. 

The code in action can be found at the [Smart Manufacturing Website](https://smartmfg.me.wisc.edu/pages/dashboards/machine_monitoring/robonano1_ms.html) from MINLab (Manufacturing Innovation Network Laboratory).

## Highlights
- The adapter was cloned from the official MTConnect repository and augmented
- FOCAS2 was used to interface with the FANUC Controller
- The adapter and the agent were deployed on Raspberry Pis
- MQTT protocol was used to transfer data from the agent to the cloud (AWS)
  - Topics were created for the following cases
    - Data transfer to AWS Services
    - Parameter Update from Cloud
    - Device Shadow updates to initiate and stop the DAQ process
- By visiting the website, the data upload is initiated by clicking on the "Connect to Machine" button

## Directory Structure

- **Machine**
  - `monitoring.py` -> Responsible for parsing and extracting the information from the XML document returned by the agent.
- **MQTT**
  - `mqtt_callbacks.py` -> Contains functions for the MQTT callbacks.
  - `mqtt_device_shadows.py` -> Contains functions for the MQTT device shadows callbacks.
- `config.yml` -> Contains the configuration for the operation status update function.
- `install_container.sh` -> Starts a container for the MTConnect agent. Refer to the MTConnect's GitHub repository (https://github.com/mtconnect/cppagent).
- `main.py` -> The main file that handles the status update process.
- `mtcagent.service` -> Service file for Linux automation. Enables the ability to automatically start the agent at reboot.
- `mtcagent_mqtt.service` -> Service file for Linux automation. Automatically starts and restarts the script necessary for the status update over MQTT.
- `start_daq.sh` -> Starts the status update process, along with performing a few cleanup tasks.
- `stop_daq.sh` -> Stops the status update process smoothly.

## Run Script

1. Ensure the agent is running (as a docker container or otherwise)
2. Update the configuration file for the agent to identify the adapter correctly
3. Update the configuration file in this repo (`config.yml`) with the right parameters
4. Configure the AWS appropriately
   1. IoT Core - To add things.
   2. Lambda function - For serverless approach to get the adapter's IP address if it is not static. **Note: This might not apply to your case. With our case being a research lab under the University's network, we were not able to set a static IP for the edge devices due to some restrictions. Hence, we use AWS as an intermediary to handle the changes in the adapter's IP address over time. Not the best approach, but it is a temporary fix at the moment.**  
   3. AWS System's Manager setup for both the agent and the adapter to continuously monitor the device's status remotely
5. Depending on how the MTConnect agent is setup, you install one or both the services (`mtcagent.service`, `mtcagent_mqtt.service`) to the RaspberryPi to enable automatic start and stop at reboot, power loss, etc.
   1. In our case, both the MTConnect agent and the Status Update run on the same device. Hence both the automation scripts were installed. The MTConnect agent runs in a Docker container. For more info, see https://github.com/mtconnect/cppagent
   2. If you need to run just the status update, install the service - `mtcagent_mqtt.service`, and ensure to update the `config.yml` file to locate the MTConnect agent correctly.
  
### Installing Linux Services

Copy the service to the appropriate location

```sh
sudo cp ./mtcagent_mqtt.service /etc/systemd/system/
```

Enable the service to automatically start at boot

```sh
sudo systemctl enable mtcagent_mqtt
```

Start the service

```sh
sudo systemctl start mtcagent_mqtt
```

Stop the service for updates, if needed

```sh
sudo systemctl stop mtcagent_mqtt
```

Check the status of the service

```sh
sudo systemctl status mtcagent_mqtt
```

## Error Codes



## TODO
- [ ] Improving the ability of the system to handle errors.
- [ ] Elaborate set of error codes for troubleshooting
- [ ] Eliminate the need to use AWS lambda functions to get the adapter IP address.
- [ ] Improving the shadow document by providing more information on the device.
- [ ] Ability to automatically update the `upload_enable` parameter on the shadow document, in case of abrupt connection interruption.
- [ ] Support for MTConnect streaming to continuously acquire data from the CNC machine using AWS Kinesis







