# MTConnect Status Update

We are using MTConnect to update the status of an Ultra-precision CNC machine - FANUC ROBONANO $\alpha$-0*i*B. The machine information can be found at the [Smart Manufacturing Website](https://smartmfg.me.wisc.edu/pages/dashboards/machine_monitoring/robonano1_ms.html) from MINLab.

## Highlights
- The adapter was cloned from the official MTConnect repository and augmented
- FOCAS2 was used to interface with the FANUC Controller
- The adapter and the agent were deployed on Raspberry Pis
- MQTT protocol was used to transfer data from the agent to the cloud (AWS)
  - Topics for data and params
  - Topics for Device Shadow updates
- By visiting the website, the data upload is initiated by clicking on the "Connect to Machine" button

## Directory Structure

- **Machine**
  - `monitoring.py` -> Responsible for parsing and extracting the information from the XML document returned by the agent.
- **MQTT**
  - `mqtt_callbacks.py` -> Contains functions for the MQTT callbacks.
  - `mqtt_device_shadows.py` -> Contains functions for the MQTT device shadows callbacks.
- `config.yml` -> Contains the configuration for the operation status update function.
- `install_container.sh` -> Starts a container for the MTConnect agent. Refer to the MTConnect's GitHub repository.
- `main.py` -> The main file to run.
- `mtcagent.service` -> Service file for Linux automation. Enables the ability to automatically start the agent at reboot.
- `mtcagent_mqtt.service` -> Service file for Linux automation. Automatically starts and restarts the script necessary for the status update over MQTT.
- `start_daq.sh` -> Starts the status update process, along with performing a few clean up tasks.
- `stop_daq.sh` -> Stops the status update process smoothly.

## Run Script

1. Ensure to have the agent running (as a docker container or otherwise)
2. Update the configuration file for the agent to identify the adapter correctly
3. Update the configuration file in this repo (`config.yml`) with the right parameters
4. Configure the AWS appropriately
   1. IoT Core - To add a things.
   2. Lambda function - For serverless approach to get the adapter's ip address if it is not static
   3. AWS System's Manager setup for both the agent and the adapter to continuously monitor the device's status remotely 
5. Ensure to be in the directory containing the `main.py` file and the script below on a terminal

```shell
python ./main.py --config=./config.yml
```

## Error Codes

## TODO
- [ ] Improving the way the configuration file (agent.cfg) is read to determine the adapter ip address.
- [ ] Improving the ability of the system to handle errors.
- [ ] Eliminate the need to use AWS lambda functions to get the adapter ip address.
- [ ] Improving the shadow document by proving more information on the device.
- [ ] Ability to automatically update the `upload_enable` parameter on the shadow document, in case of abrupt connection interruption.







