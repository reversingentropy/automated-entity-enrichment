"""Which articles are the same story: the ingest's check, on the copies found in `article` (October 2026)."""

from src.shared.stories import find_copies, story_key

ST_OLD = "https://www.straitstimes.com/singapore/courts-crime/retired-police-officer-with-distinguished-career-including-sq117-hijack-response-dies-at-86"
ST_NEW = "https://www.straitstimes.com/singapore/retired-police-officer-with-distinguished-career-including-sq117-hijack-response-dies-at-86"
TITLE = "Retired police officer with distinguished career, including SQ117 hijack response, dies at 86"


def art(id, url, title="", day="2026-10-09", **kw):
    return {"id": id, "url": url, "title": title, "pubDate": f"{day}T12:00:00+00:00", **kw}


def test_the_story_key_is_what_stays_when_an_outlet_changes_the_address():
    # The Straits Times moved 19312 between sections before the morning run stored it again as 19420
    assert story_key(ST_OLD) == story_key(ST_NEW)
    # CNA rewrote the headline in the address and kept the number
    assert story_key("https://www.channelnewsasia.com/singapore/police-identify-man-after-elderly-man-shoved-ground-over-patting-girls-head-6322146") \
        == story_key("https://www.channelnewsasia.com/singapore/police-identify-40-year-old-diner-after-assault-elderly-man-who-patted-childs-head-6322146")
    # Zaobao is on two domains
    assert story_key("https://www.zaobao.com/news/singapore/story20260802-9459040") \
        == story_key("https://www.zaobao.com.sg/news/singapore/story20260802-9459040")
    assert story_key("https://www.zaobao.com/news/singapore/story20261010-9815525") != story_key("https://www.zaobao.com/news/singapore/story20261010-9815049")


def test_a_story_met_again_at_a_new_address_is_a_copy_of_the_first():
    copies = find_copies([art(None, ST_NEW, TITLE, "2026-10-09")], [art(19312, ST_OLD, TITLE)])
    assert copies == {ST_NEW: (19312, "the same article at a new address")}


def test_the_same_title_from_the_same_outlet_within_two_days_is_a_copy():
    # CNA's archive holds one story under two numbers and two addresses
    first = art(4153, "https://www.channelnewsasia.com/singapore/seed-bank-botanic-gardens-climate-change-plant-diversity-1338316",
                "Singapore opens first seed bank to protect regional plant diversity against climate change", "2019-07-13")
    again = art(None, "https://www.channelnewsasia.com/singapore/singapore-opens-first-seed-bank-protect-regional-plant-diversity-against-climate-change-5732111",
                first["title"], "2019-07-14")
    assert find_copies([again], [first]) == {again["url"]: (4153, "the same title from the same outlet within two days")}
    # not three years later: two elections
    icao = art(1, "https://www.straitstimes.com/singapore/singapore-re-elected-to-governing-body-of-un-aviation-agency-icao",
               "Singapore re-elected to governing body of UN aviation agency ICAO", "2022-10-01")
    later = art(None, "https://www.straitstimes.com/singapore/singapore-re-elected-to-icao-council", icao["title"], "2025-09-27")
    assert find_copies([later], [icao]) == {}


def test_a_column_is_not_a_copy_of_yesterdays():
    seen = [art(i, f"https://www.straitstimes.com/singapore/st-live-news-as-it-happens-{i}", "ST Live: News as it happens", d)
            for i, d in ((1, "2026-09-01"), (2, "2026-09-13"), (3, "2026-09-28"))]
    today = art(None, "https://www.straitstimes.com/singapore/st-live-news-as-it-happens-oct", "ST Live: News as it happens", "2026-09-29")
    assert find_copies([today], seen) == {}
    # four copies of one story on one day are not a column
    silk = [art(3931 + i, f"https://www.channelnewsasia.com/singapore/silkair-be-merged-singapore-airlines-undergo-100m-investment-programme-57319{i}1",
                "SilkAir to be merged into Singapore Airlines", "2018-05-17") for i in range(4)]
    assert set(find_copies(silk, [])) == {s["url"] for s in silk[1:]}


def test_two_outlets_on_one_event_are_two_sources_and_a_shared_description_is_not_a_copy():
    cna = art(3085, "https://www.channelnewsasia.com/singapore/khaw-boon-wan-step-down-sph-media-trust-chairman-6375236",
              "Khaw Boon Wan to step down as SPH Media Trust chairman", "2026-09-10")
    st = art(None, "https://www.straitstimes.com/singapore/community/khaw-boon-wan-to-step-down-as-sph-media-trust-chairman", cna["title"], "2026-09-09")
    assert find_copies([st], [cna]) == {}
    haze = [art(3004, "https://www.straitstimes.com/singapore/air-quality-in-central-singapore-in-unhealthy-range-with-psi-at-102",
                "Air quality in central Singapore in unhealthy range with PSI at 102", "2026-09-09",
                description="Readings in other regions remain in the moderate range.")]
    next_day = art(None, "https://www.straitstimes.com/singapore/air-quality-in-central-singapore-back-in-moderate-range-as-psi-drops",
                   "Air quality in central Singapore back in moderate range as PSI drops", "2026-09-10",
                   description="Readings in other regions remain in the moderate range.")
    assert find_copies([next_day], haze) == {}


def test_copies_arriving_in_one_run_point_at_the_first_and_a_third_finds_it_through_the_second():
    a = art(None, ST_OLD, TITLE)
    b = art(None, ST_NEW, TITLE)
    c = art(None, "https://www.straitstimes.com/singapore/politics/retired-police-officer-with-distinguished-career-including-sq117-hijack-response-dies-at-86", "")
    copies = find_copies([a, b, c], [])
    assert copies == {ST_NEW: (ST_OLD, "the same article at a new address"), c["url"]: (ST_OLD, "the same article at a new address")}
    # a copy already marked: a new one goes to the first, not to the copy
    stored = [art(19312, ST_OLD, TITLE), art(19420, ST_NEW, TITLE, duplicate_of=19312)]
    assert find_copies([c], stored)[c["url"]][0] == 19312
    # an address already stored is not looked at again
    assert find_copies([art(None, ST_NEW, TITLE)], stored) == {}
