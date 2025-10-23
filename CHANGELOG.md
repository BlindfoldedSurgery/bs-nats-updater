# Changelog

## v2.1.1 (2025-10-23)

### Fix

- allow newer nats-py versions
- allow bs-config 2.x

## v2.1.0 (2025-10-11)

### Feat

- support Python 3.14

## v2.0.7 (2025-09-18)

### Fix

- relax bs-config constraints

## v2.0.6 (2025-09-12)

### Fix

- pass on allowed_updated arg

## v2.0.5 (2025-07-22)

### Fix

- **deps**: update dependency nats-py to v2.11.0

## v2.0.4 (2025-07-06)

### Fix

- use default NATS timeouts

## v2.0.3 (2025-07-06)

### Fix

- properly wait for NATS draining

## v2.0.2 (2025-06-29)

### Fix

- use simple pypi API

## v2.0.1 (2025-06-29)

### Fix

- respect allowed_updates passed to start_polling

## v2.0.0 (2025-06-28)

### BREAKING CHANGE

- NatsConfig.from_env is non-optional by default now

### Feat

- add create_updater function to encapsule type trickery

### Fix

- use correct logger name

## v1.0.1 (2025-06-28)

### Fix

- use correct version in pyproject.toml

## v1.0.0 (2025-06-28)

- Initial release
