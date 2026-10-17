FROM quay.io/keycloak/keycloak:26.8.1
ENV KC_HEALTH_ENABLED=true
COPY --chown=keycloak:keycloak infra/keycloak/capital-realm.json /opt/keycloak/data/import/capital-realm.json
