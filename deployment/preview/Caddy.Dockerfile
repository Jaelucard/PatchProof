FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f

# Official Caddy carries a low-port file capability. The preview uses port 8780
# and drops all runtime capabilities; remove the unused file capability so the
# binary remains executable under that stricter runtime policy.
USER 0
RUN setcap -r /usr/bin/caddy
COPY deployment/preview/gateway-entrypoint.sh /usr/local/bin/patchproof-gateway
RUN chmod 0555 /usr/local/bin/patchproof-gateway
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/patchproof-gateway"]
