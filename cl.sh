# Send commands to daemon. Change port 5005 to your port number if necessary
# Needs Linux "netcat" package
# Sample: ./cl.sh quit, ./cl.sh "set-mode garten"
echo $1 |  nc -N 127.0.0.1 5005
