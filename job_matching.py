"""Explainable, local-only skill overlap. Scores are not hiring probabilities."""
import re

ALIASES = {
 'Python':['python'], 'JavaScript':['javascript','js'], 'TypeScript':['typescript'],
 'Java':['java'], 'C#':['c#','c sharp'], 'C++':['c++'], 'Go':['golang','go language'],
 'Ruby':['ruby'], 'PHP':['php'], 'Rust':['rust'], 'Kotlin':['kotlin'], 'Swift':['swift'],
 'React':['react','reactjs','react.js'], 'Angular':['angular'], 'Vue':['vue','vuejs','vue.js'],
 'Next.js':['next.js','nextjs'], 'Node.js':['node.js','nodejs'], 'Django':['django'],
 'Flask':['flask'], 'FastAPI':['fastapi'], '.NET':['.net','dotnet'], 'Spring':['spring boot','spring framework'],
 'Rails':['rails'], 'HTML':['html'], 'CSS':['css','tailwind'], 'SQL':['sql'],
 'PostgreSQL':['postgresql','postgres'], 'MySQL':['mysql'], 'SQLite':['sqlite'],
 'MongoDB':['mongodb'], 'Redis':['redis'], 'AWS':['aws','amazon web services'],
 'Azure':['azure'], 'GCP':['gcp','google cloud'], 'Docker':['docker'], 'Kubernetes':['kubernetes','k8s'],
 'Terraform':['terraform'], 'Git':['git'], 'Linux':['linux'], 'REST APIs':['rest','restful'],
 'GraphQL':['graphql'], 'CI/CD':['ci/cd','continuous integration'], 'Testing':['unit tests','unit testing','pytest','jest'],
 'Playwright':['playwright'], 'Selenium':['selenium'], 'Spark':['apache spark','pyspark'],
 'Kafka':['kafka'], 'Machine learning':['machine learning','scikit-learn'],
 'PyTorch':['pytorch'], 'TensorFlow':['tensorflow'], 'Figma':['figma'],
 'Agile':['agile','scrum'], 'Elasticsearch':['elasticsearch'], 'Scala':['scala'],
 'Elixir':['elixir'], 'Dart':['dart'], 'Flutter':['flutter'], 'React Native':['react native'],
}

def contains(text, term):
    return bool(re.search(r'(?<![\w])'+re.escape(term)+r'(?![\w])',text,re.I))

def skills(text):
    found = {name for name, aliases in ALIASES.items() if any(contains(text,a) for a in aliases)}
    if re.search(r'\bGo\s+(?:developer|engineer|programming)\b',text): found.add('Go')
    return found

def role_matches(title, terms):
    title = title.lower()
    return any(term.strip().lower() in title for term in terms.split(',') if term.strip())

def match(job, settings):
    detected = skills(job.get('title','')+' '+job.get('description',''))
    owned = skills(settings.get('resume_text',''))
    matched = sorted(detected & owned)
    missing = sorted(detected - owned)
    score = round(100*len(matched)/len(detected)) if detected and owned else None
    title = job.get('title','')
    location = job.get('location','')
    wanted = settings.get('location','').strip()
    worldwide = bool(re.search(r'\b(worldwide|anywhere|global|world wide)\b',location,re.I))
    location_signal = ('Not specified' if not location else 'Location matches' if wanted and contains(location,wanted)
                       else 'Worldwide listed' if worldwide else 'Check eligibility')
    years = [int(v) for v in re.findall(r'\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*years?\s+(?:(?:of|in|for)\s+)?(?:professional\s+)?(?:experience|commercial|software|engineering|development|devops|sre|backend|frontend)',job.get('description',''),re.I)]
    minimum_years = min(years) if years else None
    experience = settings.get('experience_years')
    return {'score':score,'matched_skills':matched,'missing_skills':missing,
            'role_match':role_matches(title,settings.get('roles','engineer,developer')),
            'location_signal':location_signal,
            'minimum_years':minimum_years,
            'experience_warning':minimum_years is not None and experience is not None and minimum_years>experience,
            'seniority_warning':bool(re.search(r'\b(senior|staff|principal|lead|director)\b',title,re.I))}
