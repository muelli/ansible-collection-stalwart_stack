# Changelog

## Unreleased

- `stalwart_domains[].catch_all` sets Stalwart's catch-all address
  (`Domain.catchAllAddress`) for a domain. Leaving it out keeps the server's
  value; `null` or `""` clears it.
- caddy_front runs `caddy validate` before restarting or reloading Caddy. A bad
  config now fails the play with Caddy's own error and leaves the running Caddy
  alone; `caddy run` only exits with status 1 and the journal shows no reason.
- caddy_front's name-clash check names the clashing hostnames in its failure
  message.
- Stalwart 1.1.0 (checksums for x86_64 and aarch64), Bulwark 1.21.0 and Caddy
  v2.11.9 are the new defaults; stalwart-cli stays at 1.0.14, its latest release.
  Stalwart 1.1.0 adds passkeys, which need the new `sysPasskey*` permissions in
  default roles created by an earlier version: start the server once with
  `STALWART_UPDATE_ROLE_PERMISSIONS=true` to add them. Nothing in these roles
  needs them.

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
