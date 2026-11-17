# Stalwart behind Caddy, in five Ansible roles

| Role | Does |
| --- | --- |
| `stalwart_install` | Pinned Stalwart server and `stalwart-cli` (sha256-checked, optional sigstore check), user, systemd unit, `config.json` (data store only), fallback admin |
| `caddy_front` | Caddy from the official build service (with DNS plugins), TLS for every web name, sites for Stalwart and other domains, certificate sync to Stalwart |
| `caddy_user_instances` | Socket-activated Caddy per user, reached by the front Caddy over a `0660` UNIX socket |
| `stalwart_config` | The declarative plan (listeners, DNS providers, certificates, domains, relays, sender routing) applied with `stalwart-cli apply` |
| `bulwark` | Bulwark webmail as a Podman Quadlet container, pointed at Stalwart's public URL (optional, `bulwark_enabled`) |

Run order is fixed (`playbook.yml`): install, front Caddy (it must obtain the
certificates the plan references), user instances, then the plan.

## Use

```
cp examples/hosts.example.ini inventory/hosts.ini           # inventory/ is git-ignored
cp examples/group_vars-all.example.yml inventory/group_vars/all.yml
ansible-vault encrypt_string ...                             # secrets go in a vault
ansible-playbook -i inventory/hosts.ini playbook.yml
```

Needs ansible-core >= 2.16 on the controller; the target is Debian or Ubuntu
on x86_64 or aarch64 with systemd.

## How the pieces fit

* Caddy owns ports 80 and 443 and every certificate (DNS-01 per provider, or
  Caddy's internal CA with `caddy_tls_mode: internal` for tests).
* Stalwart's web side (admin UI, JMAP, webmail) listens on `127.0.0.1:8008`
  and expects PROXY protocol v2 from Caddy. Mail ports (25, 465, 587, 143, 993,
  4190) are served by Stalwart directly with the certificate Caddy obtained.
  `stalwart-cert-sync@<domain>.path` copies a renewed certificate to
  `/etc/stalwart/certs` and asks Stalwart to reload it.
* `caddy_domains` entries with `user: alice` are forwarded to
  `/run/caddy-user-sockets/alice.sock`. The `hosts` of a `caddy_user_instances`
  entry get such a site automatically: root decides which names go to which
  account, and everything on them is forwarded. A `caddy_domains` entry of the
  same name takes precedence (for `dns:` or other options). The DNS provider is
  the one of the longest Stalwart domain the host lies below, else none
  (HTTP-01). systemd creates that socket (mode
  `0660`, group `alice`; the front Caddy joins the group). The first request
  starts `systemd-socket-proxyd`, which starts alice's Caddy; both stop after
  `caddy_user_idle_time` without traffic.
* Stalwart is configured only through `stalwart-cli apply`. The first apply runs
  against a temporary recovery instance, later ones against a loopback-only
  listener (`127.0.0.1:8081`), falling back to recovery if that fails.
  Re-applying happens when the rendered plan changes, or with
  `-e stalwart_force_apply=true`.

## Things to know

* Written for Stalwart 1.0.x. Object fields differ from 0.16 (`Relay.host`,
  `NetworkListener.implicitTls`); the CLI has to match the server version.
* Port 80/443 must be free. `caddy_front` refuses to start Caddy otherwise (for
  example when DebOps runs Apache or nginx on the same host).
* `stalwart_conflicting_services` (default empty) lists units to stop and
  disable first, for example `[apache2, postfix, dovecot, rspamd, opendkim]`.
  On a DebOps-managed host the next `debops run` would start them again, so the
  play fails when the host is still in the matching `debops_service_*` group
  (`stalwart_check_debops_groups: false` turns that off). Use the nested groups
  of `examples/hosts.example.ini`: moving a host between `with_stalwart` and
  `without_stalwart` is the only edit needed.
* The Stalwart unit conflicts with `postfix`, `sendmail` and `exim4`.
* The plan contains DNS and relay secrets; it is written `0600` and hidden from
  Ansible output. The fallback admin password (>= 12 characters) is required.
* `sender_domain_routing` rules match `sender: user@example.org` or `sender: '@example.org'`
  (a whole domain); addresses win over domains.
* Domains with a relay in `sender_domain_routing` must not set `dns:`;
  automatic DNS would overwrite their SPF record. The role fails on that, unless
  the relay has `manages_spf: true` (it sends with its own return-path domain,
  as SMTP2GO does).
* `caddy_user_instances` expects the accounts to exist (DebOps can create them).
* New Stalwart or CLI versions need their sha256 in `stalwart_checksums` /
  `stalwart_cli_checksums`, or set `stalwart_checksum` / `stalwart_cli_checksum`.
* `stalwart_install_vandelay: true` also installs Vandelay, Stalwart's account
  migration tool (`/usr/local/bin/vandelay`, version `stalwart_vandelay_version`).
* `/usr/local/bin/stalwart-env` (root only) runs a command with the administrator login of
  `/etc/stalwart/cli.env`, whatever the shell: `stalwart-env stalwart-cli query Domain`,
  `stalwart-env vandelay export ...`.
  Run it by hand to move mail, contacts and calendars from IMAP, CalDAV,
  Maildir and others into Stalwart; no role calls it.
* `caddy_build_method` is `download` (build service, no checksum), `xcaddy` or
  `binary` (prebuilt file plus `caddy_binary_sha256`).
* `xcaddy` builds on the controller and caches the result in
  `caddy_build_cache_dir` (default `.cache/caddy`, keyed by version, modules and
  architecture). By default it runs the official `caddy:<ver>-builder` image
  with `podman run --rm`, so the controller needs only podman; the pulled image
  stays in podman's storage unless `caddy_builder_remove_image: true`. With
  `caddy_xcaddy_runner: local` it uses `xcaddy` from PATH. Entries of
  `caddy_xcaddy_modules` / `caddy_xcaddy_replaces` are the arguments of
  `--with` / `--replace`. When you pin `caddy_xcaddy_caddy_version`, pin the
  modules too: a new plugin release can require a newer Caddy and the build
  fails.

## Firewall

The roles do not touch the firewall (it differs per site). Open these TCP ports
on a host that runs them: 25, 465, 587 (SMTP), 143, 993 (IMAP), 4190
(ManageSieve), 80 and 443 (Caddy). With DebOps, put them into
`group_vars/mailservers/` of the DebOps inventory, as `ferm__dependent_rules`
(see `examples/ferm.example.yml`); that variable is not used by DebOps' own
mail roles, so it does not replace other rule lists.

## Bulwark webmail

The `bulwark` role runs the full Bulwark edition as a podman container through a
Quadlet unit (`/etc/containers/systemd/bulwark.container`), so systemd manages
it like a native service (`systemctl status bulwark`). It uses the host network,
listens on `127.0.0.1:3000`. The browser talks to Stalwart directly, so Bulwark
is pointed at `https://<stalwart_hostname>` (`bulwark_jmap_url`), never at the
loopback listener: the browser would try to reach `127.0.0.1` on its own
machine. Enable it with `bulwark_enabled: true` and `bulwark_admin_password`
(vault), and name its host:

```yaml
bulwark_enabled: true
bulwark_hostname: webmail.example.org
```

`caddy_front` then serves that name (forwarding to `bulwark_bind:bulwark_port`
with `flush_interval -1`, and the DNS provider of the Stalwart domain it lies
below) and lets it call Stalwart across origins: the Caddy site answers the CORS
preflight for `https://<bulwark_hostname>`. More origins go into
`stalwart_cors_origins`. A `caddy_domains` entry of the same name wins and is
used as written, for example to set its own `dns:` or directive.

### Automatic DNS for a subdomain of a zone

With `dns:` set Stalwart publishes the domain's records itself. It assumes the
domain is its own zone, so for `test.example.org` inside the zone `example.org`
the provider answers "Not found". Name the zone with `zone_origin`:

```yaml
stalwart_domains:
  - { name: test.example.org, state: present, dns: spaceship, zone_origin: example.org }
```

### The Stalwart host name and the mail domains

Two kinds of names belong to Stalwart, and the roles treat them differently.

* **`stalwart_hostname`** is where Stalwart listens, and what the MX and SRV
  records of every domain point at (`mail.example.org`). Everything on it goes
  to Stalwart, through its `http-proxy` listener with PROXY protocol v2 (the
  roles always create that listener and the loopback `mgmt` listener, even when
  `stalwart_server_listeners` is overridden). Stalwart serves many paths there
  (`/jmap`, `/dav`, `/auth`, `/login`, `/.well-known/*`, `/admin`, ...) and its
  documentation gives no list a front end could split on, so nothing else can be
  served on that name. It needs no `stalwart_domains` entry: it gets its site
  and a certificate that is copied to Stalwart for the mail ports.
* **The mail domains** in `stalwart_domains` are the part after the `@`. Mail
  needs only a few subdomains of them over HTTPS (`mta-sts`, `autoconfig`,
  `autodiscover`, `ua-auto-config`, `stalwart_subdomains`), which go to Stalwart,
  as in the DNS records Stalwart wants for the domain. The domain's own name is
  free for a site of yours: list it in `caddy_domains` or as a host of a
  `caddy_user_instances` site. Without one, Caddy answers 404 there.
  `serve_http: true` on an entry forwards everything on its name to Stalwart
  instead (the play then fails when a Caddy site uses the name).

After the plan is applied the roles compare the CNAME records Stalwart wants for
each domain with the subdomain sites Caddy serves, and fail when one is missing
(`stalwart_check_zone: false` turns this off; a domain that sets `subdomains`
itself is skipped). What clients still look for on the bare mail domain is
Thunderbird's fallback `/.well-known/autoconfig/mail/config-v1.1.xml`, which
comes second after `autoconfig.<domain>`; JMAP, CalDAV and CardDAV discovery
follow the SRV records to the host name.

`/` on the Stalwart host name is not served by Stalwart itself but redirected
(`Http.redirectRoot`, default `/account`); `stalwart_redirect_root` sets another
URL. After applying the plan the role runs Stalwart's `ReloadSettings` action,
since such settings are otherwise read only at startup.

Each mail domain gets one wildcard certificate (DNS-01, so it needs `dns:`;
Caddy 2.10 or newer, which prefers a wildcard certificate over per-name ones
when the config has one). The names one label below the domain (the subdomains
above and the host name when it lies there) keep their own site files but get no
certificate of their own, and the copy for Stalwart's mail ports is taken from the
wildcard certificate. The domain itself keeps its own certificate, `caddy_domains`
entries keep theirs, and unknown subdomains get a 404 from the wildcard site.
`wildcard: false` on an entry gives every name its own certificate.

```yaml
stalwart_hostname: mail.example.org
stalwart_domains:
  - { name: example.org, dns: spaceship }
caddy_user_instances:
  - name: alice
    hosts: [example.org, www.example.org]   # root forwards these to alice
    sites:
      - name: www                           # ~alice/.config/caddy/conf.d/www.conf
        directive: |                        # a website on a mail domain
          respond "Hello" 200
```

### Accounts, aliases, forwards and lists

`stalwart_accounts` and `stalwart_lists` map one to one onto Stalwart's `Account`
(type User) and `MailingList` objects. The roles do not manage credentials: a new
account has none, so it receives mail but cannot log in, and an update never
touches the password of an existing one (set it with `stalwart-cli update Account
<id> --json '{"credentials":{"0":{"@type":"Password","secret":"..."}}}'`).

```yaml
stalwart_accounts:
  - name: muelli
    domain: example.org              # a present entry of stalwart_domains
    aliases: [ebay@example.org, shop@other.example]
  - name: knochen                    # a forward needs an account to hold the script
    domain: example.org
    forward_to: someone@gmx.net      # Sieve redirect; forward_keep_copy: true keeps a copy too
stalwart_lists:
  - name: team
    domain: example.org
    recipients: [a@example.org, b@gmail.com]
stalwart_domains:
  - name: old.example.org
    catch_all: team@example.org      # a whole-domain catch-all that fans out
```

Which one to use for a Postfix `virtual_alias_maps` entry:

| Postfix target | Use |
|---|---|
| one local mailbox | `aliases` of that account |
| one external address | `forward_to` of an account |
| several addresses, local or external | a `stalwart_lists` entry |
| `@domain` to somewhere | `catch_all` of the domain, pointing at an account or list |

A Sieve redirect (`forward_to`) sends the message with the account's own address as
envelope sender and leaves the headers, DKIM signatures and body untouched, so a
receiver checking SPF sees your own domain. A list keeps the original sender in the
envelope, which fails SPF at Gmail or GMX for mail from other domains. Stalwart allows
one redirect per script by default, hence one address. The role installs the script as
the administrator (no password needed); it becomes the account's active script and
other scripts stay, inactive.

Providers that greylist (anonbox, Guerrilla Mail) accept a forward on the second
attempt, a couple of minutes later.

`aliases` is owned by the role: others are removed, `[]` removes all, leaving it out
keeps what the server has. The domains of the aliases must be present entries of
`stalwart_domains`.

Nothing is checked beforehand: the plan is applied and a failure is explained
afterwards. An alias or list on a domain that is not in `stalwart_domains`, for
example, ends the run with Stalwart's message and the names of the domains concerned.
The apply is not atomic, so objects earlier in the plan are already updated.

### Groups, shared folders, calendars and address books

A **group** (`stalwart_groups`) is an account without login that has an address of its own
(`support@`), a mailbox, a calendar and an address book. Mail to it lands in its Inbox.
Members are listed on their accounts (`groups: [support@example.org]`, Stalwart's
`memberGroupIds`): they see the group as an extra account in IMAP (`Shared Folders/<group>`),
JMAP and CalDAV/CardDAV, with full rights, and Stalwart offers them the group address as an
identity to send from.

**From header and alerts.** Stalwart makes the *envelope* sender of an authenticated user one of
their own addresses (`Must match sender`, on by default) but accepts any `From:` header, so an
account can still show another address to the recipient. `stalwart_enforce_from_header: true`
adds a DATA-stage Sieve script that refuses a message whose From address differs from the
envelope sender, or that has several From addresses (`550 5.7.1`); accounts in
`stalwart_enforce_from_header_except` are exempt. Measured over SMTP submission on Stalwart
1.1.1: the own address, with a display name or in other case, passes; another domain, another
local account and two addresses are refused. Submissions through JMAP (webmail) pass the same
DATA stage: a spoofed From is refused there too (`forbiddenToSend`, `550 5.7.1`). `stalwart_webhooks` makes Stalwart POST events (by default failed DNS
record publishing, ACME and certificate trouble) to an endpoint you run; the alerts should not
depend on the mail server they watch.

**Sharing** (`stalwart_collections`) gives one account or group access to a folder, calendar
or address book of another. It is done over JMAP as the administrator, so no password of the
owner is involved. An entry names the owner, the `kind` (`folder`, `calendar`,
`addressbook`), the `name` and optionally `share_with: {address: [rights]}`. The collection is
created if it does not exist (a folder path such as `Projects/Alpha` creates its parents) and an
existing one is found by name, so the default Inbox or default calendar can be named to manage
only their sharing. `share_with` replaces the whole sharing list of that one collection (`{}`
removes it, leaving it out keeps it). Rights are Stalwart's JMAP names (`mayReadItems`,
`mayWriteAll`, `mayRead`, ...); the full list is in the defaults. Stalwart stores a few rights
together (`mayWriteAll` also stores `mayWriteOwn`, `mayUpdatePrivate`, `mayRSVP`;
`maySetSeen` and `maySetKeywords` go together), and the role knows them, so a second run
changes nothing.

`properties:` sets other JMAP properties by their JMAP names (calendar: `color`, `description`,
`sortOrder`, `isSubscribed`, `isVisible`, `timeZone`, `isDefault`; address book: `description`,
`sortOrder`, `isSubscribed`, `isDefault`; folder: `sortOrder`, `isSubscribed`). Only the listed
ones are compared and written; one Stalwart does not know fails with its message.
`rename_from: Old name` renames in place (same folder; the id, the content and the sharing
stay) when the old name exists and `name` does not. Once renamed it does nothing, so the line
may stay; when both names exist the play fails naming both ids and touches neither.

```yaml
stalwart_groups:
  - {name: support, domain: example.org}
stalwart_accounts:
  - {name: alice, domain: example.org, groups: [support@example.org]}
  - {name: bob, domain: example.org}
stalwart_collections:
  - owner: alice@example.org
    kind: folder
    name: Projects/Alpha
    share_with:
      bob@example.org: [mayReadItems, maySetSeen]
  - {owner: support@example.org, kind: calendar, name: Rota, share_with: {bob@example.org: [mayReadItems]}}
```

What to know, all measured on Stalwart 1.1.0:

* Sharing is not inherited. A sub-folder needs its own entry (the parent of
  `Projects/Alpha` is created without any sharing).
* Sharing a mail folder with someone does not let them send as the owner. For a shared
  sending address use a group.
* Names are not unique in Stalwart. Two collections of one owner with the same name make the
  entry fail with their ids, and the role does not guess; rename or delete one yourself.
* Removing an account or group removes it from the shares on its own. A group cannot be
  deleted while an account is still a member: first run without the account's `groups`
  (or with `groups: []`), then mark the group absent. The error names the member.
* `state: absent` on a collection deletes it. A non-empty one is refused unless
  `remove_content: true`. Collections of an owner that is itself absent are skipped.
* The IMAP ACL commands are not offered (`SETACL` and `GETACL` fail), but folders shared
  this way show up under `Shared Folders/<owner>/` and `MYRIGHTS` reports the rights.

### Mail to certain addresses: switching off, spam, discard, reject

With one address per correspondent you can tell who leaked yours, and switch that address off
later. Two mechanisms, for two situations:

* **An explicit alias that refuses mail.** Give the alias as `{address: ..., enabled: false}` in
  `aliases` of an account, group or list. The address stays in the configuration but Stalwart
  answers `550 5.1.1 Mailbox does not exist` at RCPT TO. This does nothing if a domain
  `catch_all` accepts the address instead: the catch-all takes everything the aliases refuse.
* **`stalwart_recipient_policies`**, for addresses that deliver (explicit aliases or a catch-all):

  ```yaml
  stalwart_recipient_policies:
    - {address: ebay@example.org, action: spam}       # delivered to Junk
    - {address: shop@example.org, action: discard}    # accepted, silently dropped
    - {address: 'block-*@example.org', action: reject}  # refused after DATA with 550
    - {address: old@example.org, state: absent}       # remove the entry
  ```

  The role writes one lookup entry per address (namespace `rcpt-policy`), one spam rule
  (`RCPT-POLICY`, variant `Email`, which looks up every address of a message) and the three spam
  tags `RCPT_SPAM`, `RCPT_DISCARD` and `RCPT_REJECT` that carry out the action. `*` and `?` in an
  address make it a glob. Entries marked `absent` are deleted, and when no present entry is left
  the rule is switched off.

What to know, measured on Stalwart 1.1.0:

* The verdict is for the **whole message**. A mail to a listed and an unlisted address is
  rejected or discarded for both, and `spam` files it as junk for both.
* The rule looks at **every address of the message**, headers as well as envelope, so a listed
  address in `From:` or `Cc:` counts too.
* `reject` happens after DATA, not at RCPT TO (an explicit disabled alias is the way to refuse
  earlier). `discard` tells the sender the mail was queued.
* Lookup lists are read after `ReloadLookupStores`, which the role runs for you.
* The spam rule cannot see `rcpt`; `env_to` is a list. That is why the rule is of the `Email`
  variant, which gets one address at a time as `email`.

### Routing mail through a relay by sender

`sender_domain_routing` picks the relay of `stalwart_relay_hosts` for outgoing mail by the
envelope sender: `user@example.org` matches one address, `@example.org` a whole domain. This
is Postfix's `sender_dependent_relayhost_maps`; address rules win over domain rules whatever
their order in the list.

### The Caddy of a user

Each instance is bare minimum: a Caddyfile with the global options that imports
`~/.config/caddy/conf.d/*.conf`. The role writes one file there per entry of
`sites` (`state: absent` removes it again); every other file in `conf.d` belongs
to the account and is never touched, so the account can add its own sites and
configuration. Which names reach the account is decided at the root, in `hosts`
of the instance; the account then answers each host as it likes. A site's own
`hosts` default to all of them.

An entry's `state` defaults to `present`.

### Running one role

Every role is tagged with its name, so `ansible-playbook playbook.yml --tags
caddy_front` (or `debops run stalwart -l host --tags caddy_front`) runs that role
alone. `--start-at-task` does not work: the later tasks need facts that the
skipped ones compute.

### Web applications

`stalwart_applications` creates Stalwart `Application` objects: a zip bundle that
Stalwart downloads and serves under a URL prefix, next to its own `/admin` and
`/account`. After the plan is applied the roles run the `UpdateApps` action so
the bundle is fetched at once. Stalwart only accepts a single path segment as
prefix (`/app`, not `/` or `/a/b`), so an application cannot take over `/`; that
is what `stalwart_redirect_root` is for.

```yaml
stalwart_applications:
  - description: Some app
    url_prefix: [/app]
    resource_url: https://example.org/app.zip
```

### Browser apps and CORS

CORS has no parent-domain rule: a browser compares the exact origin
(`https://webmail.example.org`), so `example.org` does not cover its subdomains.
List the origins of browser apps such as Bulwark in `stalwart_cors_origins`
(`caddy_front`). Caddy then answers the preflight and sets
`Access-Control-Allow-Origin` for those origins only, replacing what Stalwart
adds, and sends no CORS headers to any other origin. Stalwart's own
`Http.usePermissiveCors` (all origins) stays off (`stalwart_permissive_cors`).

## Removing things

* Entries of `stalwart_domains`, `stalwart_accounts`, `stalwart_groups`, `stalwart_lists`,
  `stalwart_collections`, `stalwart_relay_hosts`, `stalwart_server_listeners` and `caddy_user_instances`
  accept `state: absent`. Files, systemd units, certificates, group memberships and
  the objects inside Stalwart (domain, its DKIM keys, certificate, account with its
  mail and scripts, list, relay, listener) are removed. `stalwart_absent_dns_providers`
  removes DNS providers. Deleting an account deletes its mail. `forward_to: ~`
  removes only the forwarding script.
* The default domain cannot be removed. `SystemSettings.defaultDomainId` points
  to `stalwart_default_domain`, which is the first `present` entry of
  `stalwart_domains` (it is not derived from `stalwart_hostname`, which only
  sets the default hostname). Stalwart also refuses to delete a domain that
  still has accounts. To remove the default domain, put another present entry
  first and run. Mark the domain's accounts and lists `state: absent` in the same
  run as the domain: they are removed before the domain. An account or list that
  stays makes the run fail, naming the domain.
* Removing a domain does not remove the DNS records Stalwart published for it.
  Delete them at the provider yourself. Recreating the domain publishes the
  full set again, provided `zone_origin` is right.
* Whole roles: `stalwart_install_state`, `caddy_front_state`, `bulwark_state`
  set to `absent`. Data stays unless `stalwart_purge_data`, `caddy_purge_data`
  or `bulwark_purge_data` is true. A `caddy_user_instances` entry can add
  `purge: true` and `release_linger: true`.
* `teardown.yml` removes everything in reverse order:
  `ansible-playbook teardown.yml -e stalwart_purge_data=true ...`

## Tested

Ubuntu 26.04 VM, ansible-core 2.21.5, Stalwart 1.0.0 (fresh install), 1.0.2
(upgrade from 1.0.1) and 1.1.0 (upgrade from 1.0.2, repeat run without changes),
stalwart-cli 1.0.14, Bulwark 1.21.0 (upgrade from 1.20.0; 1.20.0 came from 1.18.0,
and its readiness check cannot reach Stalwart on the VM, which has an internal
CA), Caddy v2.11.9 (upgrade from v2.11.7, xcaddy build via podman), CORS preflight
and origin allowlist through `stalwart_cors_origins`, a host name that is not a
mail domain (certificate from the parent's wildcard, valid on the IMAPS port), a
mail domain that serves a website with the subdomains still going to Stalwart, a
domain without `state`, the zone check failing when a subdomain is missing,
`bulwark_hostname` (site and CORS preflight derived from it), and
`--tags caddy_front`, Caddy with its internal CA: fresh install, repeat run
without changes,
fallback to recovery, forced apply through the management listener, web path
Caddy -> Stalwart (PROXY v2) and Caddy -> user socket -> user Caddy, socket
unreachable for other users, certificate sync and reload.
xcaddy build via podman (cache hit on the second run, plugin present in the
binary) and the DebOps group check.
Also tested: Bulwark as a Quadlet container behind Caddy, `state: absent` for
domains, relays, listeners and per-user instances, the full teardown with purge
and a fresh reinstall (second run changed nothing).
Also tested: `stalwart_applications` (create, update, `state: absent`, repeat
runs), origin-restricted CORS for Bulwark, sites derived from
`caddy_user_instances`, and on a real host: webmail login at Bulwark, a user
Caddy site with a DNS-01 certificate from Spaceship.
Not tested: push notifications (Stalwart to the Bulwark push relay), relays and
sender routing against real servers, other distributions than Ubuntu 26.04.

## Installing from Galaxy

The roles ship as the collection `muelli.stalwart_stack`:

```bash
ansible-galaxy collection install muelli.stalwart_stack
ansible-playbook -i inventory/hosts.ini muelli.stalwart_stack.site
ansible-playbook -i inventory/hosts.ini muelli.stalwart_stack.teardown
```

Roles are also usable by their FQCN, for example
`muelli.stalwart_stack.caddy_front`. Cloning the repository still works with
`playbook.yml` and `teardown.yml`, which use the short role names. Version
0.1.0 is a pre-release, see `CHANGELOG.md`.

### Releasing

Bump `version` in `galaxy.yml`, add a `## <version>` section to `CHANGELOG.md`,
commit, then `git tag v<version> && git push origin v<version>`. The Release
workflow runs the tests, builds, publishes to Galaxy and creates a GitHub
release. It needs the repository secret `GALAXY_API_KEY`.

## Tests

`tests/run.sh` needs no target host: it syntax-checks `playbook.yml` and
`teardown.yml`, parses every YAML file and template, runs the derivation of
Caddy sites from `caddy_user_instances` (`tests/user_instance_sites.yml`) with
the hosts listed once, twice and with a differing explicit entry, and runs
`ansible-lint` when installed (`var-naming` and `yaml` style rules are skipped).
Everything else was tested by hand on a VM, see above.

## License

GPL-3.0-or-later. See `LICENSE`.
