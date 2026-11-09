import tempfile
import unittest
from pathlib import Path

from outreach import find_leads

# Made-up Overpass elements for testing the filter logic only. Not real businesses.
FIXTURE = [
    {  # kept: email tag, no website
        "type": "node", "id": 1,
        "tags": {"amenity": "restaurant", "name": "Test Diner A", "email": "Owner@Test-Diner.example",
                 "addr:city": "Testville", "addr:street": "Main St", "addr:housenumber": "10"},
    },
    {  # kept: phone only, no website
        "type": "node", "id": 2,
        "tags": {"amenity": "cafe", "name": "Test Cafe B", "contact:phone": "+1 555 0100"},
    },
    {  # dropped: has a website
        "type": "node", "id": 3,
        "tags": {"amenity": "bar", "name": "Test Bar C", "email": "x@example.com", "website": "https://bar.example"},
    },
    {  # dropped: has a website under the contact: prefix
        "type": "node", "id": 4,
        "tags": {"amenity": "pub", "name": "Test Pub D", "phone": "555-0101", "contact:website": "https://pub.example"},
    },
    {  # dropped: no contact details at all
        "type": "node", "id": 5,
        "tags": {"amenity": "fast_food", "name": "Test Grill E"},
    },
    {  # dropped: no name
        "type": "node", "id": 6,
        "tags": {"amenity": "restaurant", "phone": "555-0102"},
    },
]


class FindLeadsTests(unittest.TestCase):
    def test_filter_keeps_only_contactable_businesses_without_website(self):
        leads = find_leads.collect([FIXTURE])
        names = [l["business_name"] for l in leads]
        self.assertEqual(names, ["Test Diner A", "Test Cafe B"])

    def test_email_is_lowercased_and_address_built(self):
        lead = find_leads.to_lead(FIXTURE[0])
        self.assertEqual(lead["email"], "owner@test-diner.example")
        self.assertEqual(lead["address"], "10 Main St, Testville")
        self.assertEqual(lead["category"], "restaurant")

    def test_phone_from_contact_prefix_is_used(self):
        lead = find_leads.to_lead(FIXTURE[1])
        self.assertEqual(lead["phone"], "+1 555 0100")
        self.assertEqual(lead["email"], "")

    def test_dedupes_same_osm_id_across_regions(self):
        leads = find_leads.collect([FIXTURE, FIXTURE])
        self.assertEqual(len(leads), 2)

    def test_dedupes_same_name_and_address_with_different_ids(self):
        copy = dict(FIXTURE[0], id=99)
        leads = find_leads.collect([[FIXTURE[0], copy]])
        self.assertEqual(len(leads), 1)

    def test_write_outputs_splits_email_and_phone(self):
        leads = find_leads.collect([FIXTURE])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "found"
            n_email, n_phone = find_leads.write_outputs(leads, base)
            self.assertEqual((n_email, n_phone), (1, 1))
            email_csv = (Path(tmp) / "found.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(email_csv[0], "business_name,email,category,city,website")
            self.assertEqual(email_csv[1], "Test Diner A,owner@test-diner.example,restaurant,Testville,")
            phone_csv = (Path(tmp) / "found-phone.csv").read_text(encoding="utf-8").splitlines()
            self.assertIn("Test Cafe B,+1 555 0100,cafe", phone_csv[1])

    def test_query_uses_bbox_and_food_amenities(self):
        q = find_leads.build_query((1.0, 2.0, 3.0, 4.0))
        self.assertIn("(1.0,2.0,3.0,4.0)", q)
        self.assertIn("restaurant|cafe", q)


if __name__ == "__main__":
    unittest.main()
