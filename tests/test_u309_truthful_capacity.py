from pathlib import Path
import json, re, subprocess, tempfile, unittest
from tests.test_u303_hud_render import _fixture_home, NOW
from v7_harness.coord.capacity_planner import collect_capacity_snapshot, render_html_dashboard
from v7_harness.coord.quota_sources import apply_measured_quota

class TruthfulCapacity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home, self.desk = self.root/'home', self.root/'desk'
        (self.desk/'.coord').mkdir(parents=True)
        (self.desk/'.coord/PLAN.md').write_text('# plan', encoding='utf-8')
    def tearDown(self):
        self.tmp.cleanup()
    def snap(self):
        return collect_capacity_snapshot(self.desk, home=self.home, now=NOW, persist=False)
    def page(self, snap):
        return render_html_dashboard(snap, self.root/'hud.html').read_text(encoding='utf-8')
    def js(self, code):
        return json.loads(subprocess.check_output(['node', '-e', code], text=True, encoding="utf-8"))
    def test_helpers_without_evidence_are_unknown(self):
        for name in ('luna','haiku','flash'):
            e = self.snap()['engines'][name]
            self.assertEqual(e['presence_state'], 'UNKNOWN', name)
            self.assertIsNone(e['usable_cards_capacity'], name)
            self.assertEqual(e['predictive_exhaustion']['exhaustion_risk'], 'UNKNOWN', name)
            self.assertIsNone(e['predictive_exhaustion']['predicted_tta_min'], name)
            for win in ('5h','7d'):
                self.assertIsNone(e['subscription_plan']['total_'+win+'_tokens'], name)
                self.assertIsNone(e['subscription_plan']['remaining_'+win+'_tokens'], name)
    def test_exhausted_helper_is_limited_without_safe_prediction(self):
        _fixture_home(self.home)
        e = self.snap()['engines']['luna']
        self.assertEqual(e['presence_state'], 'LIMITED')
        self.assertEqual(e['usable_cards_capacity'], 0)
        self.assertEqual(e['predictive_exhaustion']['exhaustion_risk'], 'IMMINENT_EXHAUSTION')
        self.assertEqual(e['measured']['window_5h']['used_pct'], 40.0)
    def test_flash_never_inherits_primary_pool_or_calibration(self):
        e = {'flash': {'subscription_plan':{}}}
        pool = {'used_pct':40.,'remaining_pct':60.,'resets_at':'x','reset_in_s':3600}
        cal = {'remaining_tokens':1234,'capacity_tokens':2000,'basis':'pair','samples':2}
        apply_measured_quota(e, {'antigravity':{'selected_pool':pool,'calibration':cal}}, {})
        self.assertIsNone(e['flash']['measured']['window_5h'])
        self.assertIsNone(e['flash']['measured']['calibration_5h'])
        self.assertNotIn('helper_quota', e['flash']['subscription_plan'])
    def test_flash_preserves_its_own_measured_pool(self):
        pool = {'used_pct':20.,'remaining_pct':80.,'resets_at':'x','reset_in_s':3600}
        e = {'flash': {'subscription_plan':{}}}
        apply_measured_quota(e, {'antigravity':{'helper_pool':pool}}, {})
        self.assertEqual(e['flash']['measured']['window_5h'], pool)
        self.assertIsNone(e['flash']['usable_remaining_5h_tokens'])
    def test_quota_javascript_does_not_restore_null_tokens_from_reference(self):
        page = self.page(self.snap())
        fn = page[page.index('function quota(k)'):page.index('function untilText')]
        sub = {'total_5h_tokens':None,'remaining_5h_tokens':None,'ref_total_5h_tokens':6000000,
               'total_7d_tokens':None,'remaining_7d_tokens':None,'ref_total_7d_tokens':60000000}
        q = self.js('const LINEUP_META={codex:{}}; const SNAP='+json.dumps({'engines':{'codex':{'subscription_plan':sub}}})+';'+fn+'console.log(JSON.stringify(quota("codex")));')
        for key in ('total5','rem5','total7','rem7'):
            self.assertIsNone(q[key], key)
    def test_fallback_dag_does_not_fabricate_progress(self):
        page = self.page(self.snap())
        fn = page[page.index('const defaultDagFor ='):page.index('const masterItems =')]
        result = self.js(fn+'console.log(JSON.stringify(defaultDagFor("codex","antigravity","ACTIVE")));')
        self.assertTrue(all(s['state'] in ('PLANNED','UNKNOWN') for s in result))
    def test_live_driver_states_override_card_state(self):
        steps = [{'sub_id':'U309:SP1_RESEARCH_DRAFT','state':'DONE'}, {'sub_id':'U309:SP2_MIA_DESIGN_AUDIT','state':'ACTIVE'}]
        master = {'phases':[{'phase_id':'U309','title':'Truthful capacity','state':'ACTIVE','owner_tool':'codex','reviewer':'antigravity'}],
                  'sub_schedule_driver':{'cards':{'U309':{'steps':steps}}}}
        (self.desk/'.coord/master_schedule.json').write_text(json.dumps(master), encoding='utf-8')
        cards = self.snap()['sub_process_schedule']['card_sub_schedules']
        c = next(c for c in cards if c['phase_id']=='U309')
        states = {s['sub_id']:s['state'] for s in c['sub_processes']}
        self.assertEqual(states[steps[0]['sub_id']], 'DONE')
        self.assertEqual(states[steps[1]['sub_id']], 'ACTIVE')
        self.assertEqual(states['U309:SP3_CODE_EXECUTION'], 'PLANNED')

if __name__ == '__main__': unittest.main()
