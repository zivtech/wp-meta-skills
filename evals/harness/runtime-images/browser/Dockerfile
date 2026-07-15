ARG BROWSER_BASE
FROM ${BROWSER_BASE}
USER root
WORKDIR /opt/wp-runtime
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
 && npm cache clean --force \
 && chown -R pwuser:pwuser /opt/wp-runtime
COPY browser-policy.js /opt/wp-runtime/browser-policy.js
COPY gateway-policy.js /opt/wp-runtime/gateway-policy.js
COPY request-policy.js /opt/wp-runtime/request-policy.js
RUN chmod 0444 /opt/wp-runtime/browser-policy.js /opt/wp-runtime/gateway-policy.js \
    /opt/wp-runtime/request-policy.js \
 && chown root:root /opt/wp-runtime/browser-policy.js /opt/wp-runtime/gateway-policy.js \
    /opt/wp-runtime/request-policy.js
USER pwuser
ENTRYPOINT ["sleep"]
CMD ["infinity"]
