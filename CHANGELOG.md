# Changelog

## 0.1.1

- Stalwart 1.0.2 (checksums for x86_64 and aarch64) and Bulwark 1.20.0 are the
  new defaults; upgrades from 1.0.1 and 1.18.0 tested on a VM and on a real host.
- `stalwart_relay_hosts[].manages_spf: true` skips the SPF/`dns:` check for relays
  that send with their own return-path domain (SMTP2GO). The check no longer
  fails on routing rules without a `state`.
- Applications marked `state: absent` are removed by id.
- Documented relays and sender routing in the defaults of `stalwart_config`.
- Role READMEs, which Galaxy's import requires.

## 0.1.0

First release. Pre-release quality: tested on Ubuntu 26.04 only; push
notifications through the Bulwark relay and relays/sender routing against real
servers are untested.
