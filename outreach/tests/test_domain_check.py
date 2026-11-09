import unittest

from outreach import domain_check


class DomainCheckTests(unittest.TestCase):
    def test_parse_dig_output(self):
        out = '"v=spf1 include:_spf.google.com ~all"\n"unrelated"\n'
        self.assertEqual(domain_check.parse_txt(out), ["v=spf1 include:_spf.google.com ~all"])

    def test_parse_nslookup_output(self):
        out = 'example.com\ttext = "v=DMARC1; p=none"\n'
        self.assertEqual(domain_check.parse_txt(out), ["v=DMARC1; p=none"])

    def test_all_present(self):
        records = {
            "example.com": ["v=spf1 -all"],
            "default._domainkey.example.com": ["v=DKIM1; k=rsa; p=ABC"],
            "_dmarc.example.com": ["v=DMARC1; p=none"],
        }
        result = domain_check.check_domain("example.com", lookup=lambda n: records.get(n, []))
        self.assertEqual(result, {"SPF": "ok", "DKIM": "ok", "DMARC": "ok"})

    def test_all_missing(self):
        result = domain_check.check_domain("example.com", lookup=lambda n: [])
        self.assertTrue(all(v.startswith("missing") for v in result.values()))

    def test_no_dns_tool(self):
        self.assertEqual(domain_check.check_domain("x.test", lookup=lambda n: None),
                         {"error": "no dig or nslookup found on this machine"})


if __name__ == "__main__":
    unittest.main()
