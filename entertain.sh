#!/usr/bin/with-contenv bash
0<&- script -qefc "/usr/bin/openssl s_server -dtls -accept 2100 -nocert -psk_identity ${USERNAME} -psk ${CLIENTKEY} -quiet | socat - tcp4-listen:7777,reuseaddr,fork" /dev/null | cat
