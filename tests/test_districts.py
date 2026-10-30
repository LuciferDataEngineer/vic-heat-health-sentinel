from vhhs.districts import district_for


def test_named_councils_keep_their_published_threshold():
    assert district_for("Latrobe (Vic.)", -38.2)[:2] == ("West and South Gippsland", 30.0)
    assert district_for("Mildura", -34.2)[:2] == ("Mallee", 34.0)
    assert district_for("Moreland", -37.7)[0] == "Central"
    assert district_for("Bayside (Vic.)", -37.9)[2] == "health.vic"
    assert district_for("Yarriambiack", -36.0)[:2] == ("Wimmera", 32.0)


def test_unincorporated_land_is_flagged():
    district, threshold, how = district_for("Unincorporated Vic", -37.5)
    assert how == "latitude-fallback"
    assert threshold == 30.0
    assert district == "Central"
