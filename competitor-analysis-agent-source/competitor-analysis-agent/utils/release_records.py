"""Keep release identities together; never combine a version with another source's date."""

def release_records(data):
    records = []
    cl = data.get('changelog') or {}
    if cl.get('latest_version') and cl.get('_source') != 'llm' and 'changelog' not in (data.get('_llm_filled_fields') or []) and data.get('_source') != 'llm_fallback':
        records.append({'platform': '官网（平台未确认）', 'version': cl['latest_version'], 'date': cl.get('latest_release_date'), 'url': ((data.get('_field_evidence') or {}).get('changelog') or [''])[0]})
    app = data.get('app_store') or {}
    if app.get('version'):
        records.append({'platform': 'iOS / ' + app.get('country', 'cn'), 'version': app['version'], 'date': app.get('release_date'), 'url': app.get('_url', '')})
    # Search-selected repositories are not proof of official product identity.
    gh = data.get('github_releases') or {}
    if gh.get('official_verified'):
        for rel in gh.get('releases') or []:
            if rel.get('tag') and not rel.get('draft') and not rel.get('prerelease'):
                records.append({'platform': 'GitHub / ' + gh.get('repo', ''), 'version': rel['tag'], 'date': rel.get('published_at'), 'url': rel.get('url', '')})
    return records
