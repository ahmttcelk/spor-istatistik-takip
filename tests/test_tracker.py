import copy
import datetime as dt
import io
import json
import unittest
from unittest.mock import patch
from cryptography.fernet import InvalidToken
from scripts.tracker import (SafeError, Store, cipher_for, number, load_alerts, metric,
    deliver_once, run_tracking, in_window, Feed)

NOW = dt.datetime(2026,10,31,1,0,tzinfo=dt.timezone.utc)
RULE = {"id":"rule-1","enabled":True,"league":"nba","scope":"player","team_id":"1",
        "player_id":"9","stat":"points","op":">=","threshold":20}
EVENT = {"id":"123","date":"2026-10-31T00:00:00Z","status":{"type":{"state":"pre"}},
         "competitions":[{"competitors":[{"team":{"id":"1","displayName":"Team"}}]}]}
SUMMARY = {"header":{"id":"123","competitions":[{"id":"123",
    "date":EVENT["date"],"status":{"type":{"state":"in"}},
    "competitors":[{"team":{"id":"1","displayName":"Team"},"score":"55"}]}]},
    "boxscore":{"players":[{"team":{"id":"1"},"statistics":[
        {"keys":["points","rebounds"],"athletes":[
            {"athlete":{"id":"9","displayName":"Player"},"didNotPlay":False,"stats":["25","8"]}]}]}]}}
class MemoryStore:
    def __init__(self):
        self.state={"delivered":{},"completed":{},"fixtures":{},"budget":{}}
        self.snapshots=[]
    def save(self):
        self.snapshots.append(copy.deepcopy(self.state))
class FakeFeed:
    def __init__(self, summary=None):
        self.payload=copy.deepcopy(SUMMARY if summary is None else summary)
        self.calls=0
    def fixtures(self, league):
        return [copy.deepcopy(EVENT)]
    def summary(self, league, ident):
        self.calls+=1
        return self.payload
class TrackerTests(unittest.TestCase):
    def test_invalid_json_does_not_expose_preferences(self):
        with self.assertRaises(SafeError) as ctx:
            load_alerts('PRIVATE_SENTINEL')
        self.assertNotIn("PRIVATE_SENTINEL",str(ctx.exception))
    def test_empty_config(self):
        self.assertEqual(load_alerts("[]"),[])
    def test_unsupported_euroleague_fails_closed(self):
        rule=dict(RULE,league="euroleague")
        with self.assertRaises(SafeError):
            load_alerts(json.dumps([rule]))
    def test_duplicate_rule_ids_rejected(self):
        with self.assertRaises(SafeError):
            load_alerts(json.dumps([RULE,RULE]))
    def test_numeric_zero_is_valid_missing_is_not(self):
        self.assertEqual(number("0"),0)
        self.assertIsNone(number("--"))
        self.assertIsNone(number("DNP"))
        self.assertIsNone(number("NaN"))
        self.assertIsNone(number(True))
    def test_nba_real_stat_alignment(self):
        self.assertEqual(metric(SUMMARY,RULE),25)
        self.assertEqual(metric(SUMMARY,dict(RULE,stat="rebounds")),8)
    def test_missing_stat_not_zero(self):
        self.assertIsNone(metric(SUMMARY,dict(RULE,stat="assists")))
    def test_dnp_skipped(self):
        summary=copy.deepcopy(SUMMARY)
        summary["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["didNotPlay"]=True
        self.assertIsNone(metric(summary,RULE))
    def test_wrong_player_skipped(self):
        self.assertIsNone(metric(SUMMARY,dict(RULE,player_id="99")))
    def test_team_score_is_match_score(self):
        self.assertEqual(metric(SUMMARY,dict(RULE,scope="team")),55)
    def test_soccer_player_goals_and_missing_data(self):
        summary=copy.deepcopy(SUMMARY)
        summary["rosters"]=[{"team":{"id":"1"},"roster":[
            {"athlete":{"id":"9"},"starter":True,"stats":[{"name":"totalGoals","value":0}]}]}]
        rule=dict(RULE,league="tur.1",stat="goals")
        self.assertEqual(metric(summary,rule),0)
        self.assertIsNone(metric(summary,dict(rule,stat="assists")))
        summary["rosters"][0]["roster"][0]["starter"]=False
        self.assertIsNone(metric(summary,rule))
    def test_encryption_hides_preferences(self):
        cipher=cipher_for("FAKE_TEST_TOKEN")
        message=b'{"private_team":"PRIVATE_SENTINEL"}'
        encrypted=cipher.encrypt(message)
        self.assertNotIn(b"PRIVATE_SENTINEL",encrypted)
        self.assertEqual(cipher.decrypt(encrypted),message)
        with self.assertRaises(InvalidToken):
            cipher_for("DIFFERENT_FAKE_TOKEN").decrypt(encrypted)
    def test_persist_before_send_and_same_match_only_once(self):
        store=MemoryStore()
        sent=[]
        def send(text):
            self.assertEqual(len(store.snapshots),1)
            self.assertIn("reserved",store.snapshots[0]["delivered"].values())
            sent.append(text)
        self.assertTrue(deliver_once(store,RULE,"123","test",send))
        self.assertFalse(deliver_once(store,RULE,"123","test",send))
        self.assertEqual(sent,["test"])
    def test_send_timeout_does_not_duplicate_on_next_run(self):
        store=MemoryStore()
        calls=[]
        def timeout(text):
            calls.append(1)
            raise SafeError("timeout")
        with self.assertRaises(SafeError):
            deliver_once(store,RULE,"123","test",timeout)
        self.assertFalse(deliver_once(store,RULE,"123","test",timeout))
        self.assertEqual(len(calls),1)
    def test_failed_persistence_prevents_send(self):
        store=MemoryStore()
        sent=[]
        with patch.object(store,"save",side_effect=SafeError("conflict")):
            with self.assertRaises(SafeError):
                deliver_once(store,RULE,"123","test",sent.append)
        self.assertEqual(sent,[])
    def test_complete_poll_twice_one_delivery(self):
        store=MemoryStore()
        feed=FakeFeed()
        sent=[]
        run_tracking(store,[RULE],NOW,feed,sent.append)
        run_tracking(store,[RULE],NOW,feed,sent.append)
        self.assertEqual(len(sent),1)
        self.assertEqual(feed.calls,1)
    def test_pregame_and_finished_never_trigger(self):
        for state in ("pre","post"):
            summary=copy.deepcopy(SUMMARY)
            summary["header"]["competitions"][0]["status"]["type"]["state"]=state
            sent=[]
            run_tracking(MemoryStore(),[RULE],NOW,FakeFeed(summary),sent.append)
            self.assertEqual(sent,[])
    def test_outside_window_no_summary_request(self):
        feed=FakeFeed()
        run_tracking(MemoryStore(),[RULE],NOW+dt.timedelta(days=1),feed,lambda text: self.fail())
        self.assertEqual(feed.calls,0)
    def test_wrong_event_id_no_delivery(self):
        summary=copy.deepcopy(SUMMARY)
        summary["header"]["id"]="999"
        sent=[]
        run_tracking(MemoryStore(),[RULE],NOW,FakeFeed(summary),sent.append)
        self.assertEqual(sent,[])
    def test_missing_zero_threshold_does_not_trigger(self):
        rule=dict(RULE,stat="assists",op="<=",threshold=0)
        sent=[]
        run_tracking(MemoryStore(),[rule],NOW,FakeFeed(),sent.append)
        self.assertEqual(sent,[])
    def test_dry_run_never_sends_or_reserves(self):
        store=MemoryStore()
        with patch("sys.stdout",new_callable=io.StringIO):
            run_tracking(store,[RULE],NOW,FakeFeed(),lambda text:self.fail(),True)
        self.assertEqual(store.state["delivered"],{})
    def test_fixture_cache_once_per_day(self):
        store=MemoryStore()
        feed=Feed(store,NOW)
        payload={"leagues":[{"slug":"nba"}],"events":[EVENT]}
        with patch.object(feed,"get",return_value=payload) as get:
            self.assertEqual(len(feed.fixtures("nba")),1)
            self.assertEqual(len(feed.fixtures("nba")),1)
            self.assertEqual(get.call_count,3)
    def test_budget_stops_before_network(self):
        store=MemoryStore()
        store.state["budget"]={"date":NOW.date().isoformat(),"used":450}
        with patch("scripts.tracker.http_json") as net:
            with self.assertRaises(SafeError):
                Feed(store,NOW).get("nba","scoreboard")
            net.assert_not_called()
    def test_damaged_existing_state_never_reinitializes(self):
        store=Store("owner/repo","FAKE_GH","FAKE_BOT","abc")
        with patch.object(store,"api",side_effect=[{"object":{"sha":"abc"}},None]):
            with self.assertRaises(SafeError):
                store.load()

if __name__ == "__main__":
    unittest.main()
