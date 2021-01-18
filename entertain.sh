#!/bin/bash
0<&- script -qefc "/usr/bin/openssl s_server -dtls -accept 2100 -nocert -psk_identity fd0d4dd4-7a39-41e9-aab4-c1b57005b516 -psk 144354EDFD504621A820ACD4370C9EA9 | nc -lk -p 7777" /dev/null | cat
