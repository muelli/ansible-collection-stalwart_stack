#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+

DOCUMENTATION = r"""
---
module: stalwart_collection
short_description: Manage a folder, calendar or address book of a Stalwart account or group, and who it is shared with
description:
  - Works as the administrator over JMAP (Mailbox, Calendar, AddressBook), so no password of the owner is needed.
  - A missing collection is created (a folder path such as C(Projects/Alpha) creates missing parents).
    An existing one is found by name; two collections with the same name are an error, not a guess.
  - C(share_with) replaces the whole sharing list of that one collection. Leave it out to keep the sharing as it is.
  - Stalwart does not inherit sharing to sub-folders; each folder has its own list.
options:
  url: {description: "URL of the management listener, for example http://127.0.0.1:8081.", required: true, type: str}
  user: {description: "Administrator.", required: true, type: str}
  password: {description: "Administrator's password.", required: true, type: str}
  owner: {description: "Address (name@domain) of the account or group that owns the collection.", required: true, type: str}
  principal_ids: {description: "Map of address to Stalwart id for every account and group (as the role's stalwart_account_ids).", required: true, type: dict}
  kind: {description: "What the collection is.", required: true, type: str, choices: [folder, calendar, addressbook]}
  name: {description: "Name of the collection; for a folder a path separated by /.", required: true, type: str}
  share_with:
    description:
      - Map of address (account or group) to the list of JMAP rights granted, for example C(mayReadItems).
      - An empty map removes all sharing.
    type: dict
  state: {description: "absent deletes the collection.", choices: [present, absent], default: present, type: str}
  remove_content:
    description: "With state=absent: also delete the mail, events or contacts in it (otherwise Stalwart refuses to delete a non-empty one)."
    type: bool
    default: false
author: muelli.stalwart_stack
"""

import base64
import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url

USING = [
    "urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail", "urn:ietf:params:jmap:calendars",
    "urn:ietf:params:jmap:contacts", "urn:ietf:params:jmap:principals",
]
KINDS = {
    "folder": ("Mailbox", ["name", "parentId", "shareWith"], "onDestroyRemoveEmails"),
    "calendar": ("Calendar", ["name", "shareWith"], "onDestroyRemoveEvents"),
    "addressbook": ("AddressBook", ["name", "shareWith"], "onDestroyRemoveContents"),
}


class Api:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()

    def call(self, name, args):
        body = json.dumps({"using": USING, "methodCalls": [[name, args, "0"]]}).encode()
        r = open_url(self.url + "/jmap", data=body, method="POST", force_basic_auth=False, timeout=30,
                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        method, res, _tag = json.loads(r.read())["methodResponses"][0]
        if method == "error":
            raise RuntimeError("%s: %s" % (res.get("type"), res.get("description")))
        return res


# Rights Stalwart 1.1.0 stores together with another one (measured by granting each right alone):
# granting the key stores the values as well, so a read-back lists more than what was asked for.
IMPLIED = {
    "maySetSeen": ("maySetKeywords",),
    "maySetKeywords": ("maySetSeen",),
    "mayWriteAll": ("mayWriteOwn", "mayUpdatePrivate", "mayRSVP"),
}


def with_implied(rights):
    out = set(rights)
    for r in rights:
        out.update(IMPLIED.get(r, ()))
    return sorted(out)


def rights_of(share):
    """{principal: sorted granted rights} from what the server returns (all rights, true or false)."""
    return dict((p, sorted(k for k, v in (r or {}).items() if v)) for p, r in (share or {}).items())


def main():
    m = AnsibleModule(
        argument_spec=dict(
            url=dict(type="str", required=True),
            user=dict(type="str", required=True),
            password=dict(type="str", required=True, no_log=True),
            owner=dict(type="str", required=True),
            principal_ids=dict(type="dict", required=True),
            kind=dict(type="str", required=True, choices=sorted(KINDS)),
            name=dict(type="str", required=True),
            share_with=dict(type="dict"),
            state=dict(type="str", default="present", choices=["present", "absent"]),
            remove_content=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
    )
    p = m.params
    ids = p["principal_ids"]

    def pid(addr, what):
        if addr not in ids:
            m.fail_json(msg="%s '%s' is not an account or group of the server (is it in stalwart_accounts or "
                            "stalwart_groups, and was the plan applied?)" % (what, addr))
        return ids[addr]

    obj, props, destroy_flag = KINDS[p["kind"]]
    api = Api(p["url"], p["user"], p["password"])
    try:
        owner = pid(p["owner"], "Owner")
        want = None
        if p["share_with"] is not None:
            want = dict((pid(a, "Shared with"), sorted(r or [])) for a, r in p["share_with"].items())
        listing = api.call(obj + "/get", {"accountId": owner, "ids": None, "properties": props})["list"]

        # Find the collection; a folder is looked up segment by segment.
        segs = p["name"].split("/") if p["kind"] == "folder" else [p["name"]]
        parent, found, missing_from = None, None, 0
        for i, seg in enumerate(segs):
            hits = [c for c in listing if c["name"] == seg and (c.get("parentId") if p["kind"] == "folder" else None) == parent]
            if len(hits) > 1:
                m.fail_json(msg="%d %ss named '%s' in %s (ids %s): rename or delete the extra ones, "
                                "the role will not guess which is meant" % (len(hits), p["kind"], seg, p["owner"], ", ".join(h["id"] for h in hits)))
            if not hits:
                missing_from = i
                break
            parent, found = hits[0]["id"], hits[0]
            missing_from = i + 1

        if p["state"] == "absent":
            if missing_from < len(segs):
                m.exit_json(changed=False)
            if not m.check_mode:
                a = {"accountId": owner, "destroy": [found["id"]]}
                if p["remove_content"]:
                    a[destroy_flag] = True
                r = api.call(obj + "/set", a)
                if r.get("notDestroyed"):
                    m.fail_json(msg="Stalwart refused to delete %s '%s' of %s: %s. With remove_content: true "
                                    "the mail, events or contacts in it are deleted too." % (p["kind"], p["name"], p["owner"], json.dumps(r["notDestroyed"])))
            m.exit_json(changed=True)

        changed = False
        if missing_from < len(segs):
            changed = True
            if not m.check_mode:
                for i in range(missing_from, len(segs)):
                    c = {"name": segs[i]}
                    if p["kind"] == "folder":
                        c["parentId"] = parent
                    if i == len(segs) - 1 and want is not None:
                        c["shareWith"] = dict((k, dict((x, True) for x in v)) for k, v in want.items())
                    r = api.call(obj + "/set", {"accountId": owner, "create": {"n": c}})
                    if r.get("notCreated"):
                        m.fail_json(msg="Stalwart refused to create %s '%s' of %s: %s" % (p["kind"], segs[i], p["owner"], json.dumps(r["notCreated"])))
                    parent = r["created"]["n"]["id"]
            m.exit_json(changed=True)

        if want is not None and rights_of(found.get("shareWith")) != dict((k, with_implied(v)) for k, v in want.items()):
            changed = True
            if not m.check_mode:
                share = dict((k, dict((x, True) for x in v)) for k, v in want.items())
                r = api.call(obj + "/set", {"accountId": owner, "update": {found["id"]: {"shareWith": share}}})
                if r.get("notUpdated"):
                    m.fail_json(msg="Stalwart refused the sharing of %s '%s' of %s: %s" % (p["kind"], p["name"], p["owner"], json.dumps(r["notUpdated"])))
        m.exit_json(changed=changed)
    except Exception as e:  # network, auth, unexpected response
        m.fail_json(msg="Stalwart management API: %s" % e)


if __name__ == "__main__":
    main()
