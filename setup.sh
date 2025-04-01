#!/bin/bash
kill_processes_on_port() {
  local port="$1"
  local force_kill="$2"
  local pids=$(ss -tulpn | awk -v port_num="$port"\
  '/:'"$port"'/ {split($7, a, "=");split(a[2], b, ",");print b[1];}'| head -n 1)

  if [ -n "$pids" ]; then
    kill -9 $pids
    if [ $? -eq 0 ]; then
      echo "Forcefully killed processes $pids on port $port."
    else
      echo "Error killing processes $pids on port $port."
    fi
  else
    echo "No processes found using port $port."
  fi
}

port_forward(){
  local lport="$1"
  local rport="$2"
  local ssh_pid
  kill_processes_on_port "$lport" -9

  sshpass -p "a3ilab@nycu" \
  ssh -o ExitOnForwardFailure=yes \
   -o PubkeyAuthentication=no -o PreferredAuthentications=password\
   -NfL localhost:"$lport":localhost:"$rport" \
   a3ilab01@60.248.128.140 -p 32297 &

  if [ $? -eq 0 ]; then
    local lsof_output=""
    for i in {1..10}; do
      lsof_output=$(sudo lsof -i :"$lport")
      if [ -n "$lsof_output" ]; then
        local ssh_pid=$(echo "$lsof_output" | awk 'NR==2 {print $2}')
        break
      fi
      sleep 1
    done
    if [ -z "$lsof_output" ]; then
      echo "Error: Failed to get tunnel PID after 10 seconds."
      return 1 # Indicate failure
    fi
    echo "Loclal port $lport forwarded to remote port $rport. PID: $ssh_pid"
    return 0
  else
    echo "Failed to forward local port $lport to remote port $rport."
    return 1
  fi
}

port_forward 9999 7777
port_forward 8265 8265

