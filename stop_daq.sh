#!/bin/bash

# Get Process PID
process_pid=$(</home/minlab/mtconnect-statusUpdate/metadata/daq_run.meta)
# Send the interrupt signal
kill -SIGINT "$process_pid"
# If process cannot be found
if [ $? -eq 0 ]; then
  shutdown_state=0
else
  shutdown_state=-1
fi
echo "Shutdown Initiated"

timer=0
termination_request=1
# Check for running process
ps -p "$process_pid" > /dev/null
while [ $? -eq 0 ]
    do
      sleep 1
      timer=$((timer+1))

      # If it is taking too long
      if [ "$timer" -eq 100 ]; then
        echo "Sending a 2nd Interrupt signal"
        kill -SIGINT "$process_pid"
        shutdown_state=-2
      else
        sleep 1
      fi

      # If it is taking way too long
      if [ "$timer" -gt 200 ]; then
        echo "Sending Termination signal, Count=$termination_request"
        kill -SIGTERM "$process_pid"
        termination_request=$((termination_request + 1))
        shutdown_state=-3
      else
        sleep 2
      fi

      # Do a check
      ps -p "$process_pid" > /dev/null
    done
echo "Shutdown Complete"
