---
id: KB0006
title: VPN connection troubleshooting (GlobalProtect)
category: Network
---

# VPN connection troubleshooting (GlobalProtect)

Symptoms: VPN will not connect, authentication failed, Error 809, Error 691, gateway timeout, VPN keeps disconnecting, connected but cannot reach internal sites.

## Steps

1. Confirm your home internet works by opening a public website.
2. Fully quit and restart the GlobalProtect client, then reconnect.
3. Choose the nearest gateway; if it fails, try the alternate gateway from the drop-down.
4. Authentication failed: check your password has not expired and approve the MFA prompt.
5. Error 809 usually means a router is blocking VPN traffic - try a mobile hotspot.
6. Heavy load on Monday mornings can hit the concurrent-session limit; wait a few minutes and retry.
7. Still failing: attach a screenshot of the error to the ticket for Network Operations.

## Escalation

If the steps above do not fix it, reply to your ticket with what you tried.
