# Start the docker container
docker run --name agent --restart unless-stopped -it -p 5001:5000/tcp -v /home/minlab/mtconnect/conf:/mtconnect/config -v /home/minlab/mtconnect/log:/mtconnect/log vselvaraj92/mtcagent

