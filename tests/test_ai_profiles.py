import json
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_profiles as ai

class ResearchTests(unittest.TestCase):
    def test_unsafe_source_links_are_rejected(self):
        for url in ('javascript:alert(1)','data:text/html,test','http://localhost/path','https://user:pass@example.com','http://[invalid'):
            self.assertEqual(ai.safe_url(url),'')

    def test_research_grounds_fields_in_sources(self):
        evidence='Official information https://example.com/about and https://example.com/careers'
        profile={'summary':'Example builds software.', 'careers_url':'https://example.com/careers',
                 'suggested_steps':['Review requirements.'], 'sources':[{'title':'About','url':'https://example.com/about'}]}
        for key in ai.FACTS:profile[key]={'value':'Invented unsupported fact','source_url':'https://made-up.example'}
        profile['industry']={'value':'Software','source_url':'https://example.com/about'}
        with patch.object(ai,'configuration',return_value={'key':'secret','model':ai.DEFAULT_MODEL}), patch.object(ai,'completion',side_effect=[evidence,json.dumps(profile)]) as completion:
            result=ai.research({'name':'Example','url':'https://example.com'})
        self.assertEqual(result['industry']['value'],'Software')
        self.assertEqual(result['company_size']['value'],'Not found')
        self.assertEqual(result['careers_url'],'https://example.com/careers')
        self.assertEqual(completion.call_count,2)
        self.assertIn('tools',completion.call_args_list[0].kwargs)
        self.assertNotIn('response_format',completion.call_args_list[0].kwargs)
        self.assertIn('response_format',completion.call_args_list[1].kwargs)

    def test_no_key_and_no_sources_fail_clearly(self):
        with patch.object(ai,'configuration',return_value={'key':'','model':ai.DEFAULT_MODEL}):
            with self.assertRaisesRegex(ai.ResearchError,'Connect Groq'):ai.research({'name':'Example','url':'https://example.com'})
        with patch.object(ai,'configuration',return_value={'key':'secret','model':ai.DEFAULT_MODEL}), patch.object(ai,'completion',side_effect=['Unsupported research',json.dumps({'sources':[]})]):
            with self.assertRaisesRegex(ai.ResearchError,'source links'):ai.research({'name':'Example','url':'https://example.com'})

if __name__=='__main__':unittest.main()
