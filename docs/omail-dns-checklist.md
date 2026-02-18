# Omail DNS Checklist

## Decision: Self-Hosted SMTP on Non-DO VPS

Since DigitalOcean blocks SMTP ports (25/465/587), email will be self-hosted on a separate VPS that permits SMTP traffic.

## Current DNS Records (Existing)

The domain already has email DNS records pointing to Titan Email:

| Type | Host | Value |
|------|------|-------|
| MX | orcest.ai | mx1.titan.email (priority 10) |
| MX | orcest.ai | mx2.titan.email (priority 20) |
| TXT | orcest.ai | v=spf1 include:spf.titan.email ~all |
| TXT | orcest.ai | DKIM key (Titan) |

## DNS Records for Self-Hosted SMTP

When migrating to self-hosted SMTP, update the following DNS records via Name.com:

### 1. MX Records
```
Type: MX
Host: mail
Value: mail.orcest.ai
Priority: 10
TTL: 3600
```

### 2. SPF Record
```
Type: TXT
Host: orcest.ai
Value: v=spf1 ip4:<MAIL_SERVER_IP> include:spf.titan.email ~all
TTL: 3600
```
(Keep Titan SPF if still using it for some addresses)

### 3. DKIM Record
Generate DKIM keys on the mail server, then add:
```
Type: TXT
Host: mail._domainkey
Value: v=DKIM1; k=rsa; p=<PUBLIC_KEY>
TTL: 3600
```

### 4. DMARC Record
```
Type: TXT
Host: _dmarc
Value: v=DMARC1; p=quarantine; rua=mailto:admin@danial.ai; pct=100
TTL: 3600
```

### 5. A Record for Mail Server
```
Type: A
Host: mail
Value: <MAIL_SERVER_IP>
TTL: 300
```

### 6. PTR Record (Reverse DNS)
Configure on the VPS provider's control panel:
```
IP: <MAIL_SERVER_IP>
PTR: mail.orcest.ai
```

## Automation via Name.com API

```bash
NAMECOM_USER="danial.samiei@gmail.com"
NAMECOM_TOKEN="<token>"

# Create MX record
curl -X POST -u "$NAMECOM_USER:$NAMECOM_TOKEN" \
  "https://api.name.com/v4/domains/orcest.ai/records" \
  -d '{"type":"MX","host":"","answer":"mail.orcest.ai","priority":10,"ttl":3600}'

# Create DMARC record
curl -X POST -u "$NAMECOM_USER:$NAMECOM_TOKEN" \
  "https://api.name.com/v4/domains/orcest.ai/records" \
  -d '{"type":"TXT","host":"_dmarc","answer":"v=DMARC1; p=quarantine; rua=mailto:admin@danial.ai; pct=100","ttl":3600}'
```

## Recommended Self-Hosted Mail Stack

1. **Mail Server**: Mailu or Mail-in-a-Box
2. **Webmail UI**: Roundcube at mail.orcest.ai (deployed on Render or same VPS)
3. **VPS Provider**: Hetzner, OVH, or Vultr (all allow SMTP)

## Pre-Flight Checklist

- [ ] Provision VPS with SMTP-friendly provider
- [ ] Install mail server (Mailu/Mail-in-a-Box)
- [ ] Generate DKIM keys
- [ ] Update MX records
- [ ] Update SPF record
- [ ] Add DKIM TXT record
- [ ] Add DMARC TXT record
- [ ] Set PTR record on VPS
- [ ] Test with mail-tester.com (aim for 9+/10 score)
- [ ] Deploy Roundcube webmail at mail.orcest.ai
- [ ] Create admin@orcest.ai mailbox
