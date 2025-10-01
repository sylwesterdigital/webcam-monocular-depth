#!/usr/bin/env bash
echo " Starting Reverse Proxy Tunel to https://flaboy.com/livedepth"
ssh -p 18021 -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:9001:127.0.0.1:8443 \
  -R 127.0.0.1:9002:127.0.0.1:8765 \
  root@yolo.cx

