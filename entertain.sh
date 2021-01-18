#!/usr/bin/with-contenv bash
0<&- script -qefc "/usr/bin/openssl s_server -dtls -accept 2100 -nocert -psk_identity ${USERNAME} -psk ${CLIENTKEY} -quiet | nc -lk -p 7777" /dev/null | cat
