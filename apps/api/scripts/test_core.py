#!/usr/bin/env python3
"""Quick import + render test for SoyMutDB Next backend modules.

Run from apps/api directory: python3 scripts/test_core.py
"""
import sys
import os

# Ensure app is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    # 1. Compat (StrEnum backport)
    from app.core.compat import StrEnum
    print("1. compat.StrEnum OK:", StrEnum)

    # 2. Widget engine (import directly to avoid SQLAlchemy dependency for core test)
    import importlib
    engine_mod = importlib.import_module('app.widgets.engine')
    WidgetEngine = engine_mod.WidgetEngine
    sanitize_html = engine_mod.sanitize_html
    render_error_fragment = engine_mod.render_error_fragment
    get_engine = engine_mod.get_engine
    print("2. WidgetEngine import OK")

    # 3. Sanitization security test
    bad = '<script>alert(1)</script><b>bold</b><strong>strong</strong><a href="javascript:xss()">click</a><div data-id="123" class="foo" onmouseover="bad()">text</div>'
    clean = sanitize_html(bad)
    assert '<script>' not in clean, 'SCRIPT TAG NOT STRIPPED'
    assert 'onmouseover' not in clean, 'EVENT HANDLER NOT STRIPPED'
    assert 'javascript:' not in clean, 'JS URL NOT STRIPPED'
    assert '<strong>strong</strong>' in clean, 'STRONG TAG STRIPPED'
    assert 'data-id="123"' in clean or 'data-id' in clean, 'data-* ATTR STRIPPED'
    print("3. Sanitization PASSED (script/event/js-url stripped, strong/data-* preserved)")

    # 4. List templates
    engine = get_engine()
    templates = engine.list_builtin_templates()
    print(f"4. Built-in templates ({len(templates)}):", templates)
    assert 'sra_run' in templates, 'sra_run.html template not found'
    assert 'hero' in templates
    assert 'stats' in templates

    # 5. Error fragment
    err_html = render_error_fragment('test_widget', 'something went wrong')
    assert 'widget-error' in err_html
    print("5. Error fragment OK:", len(err_html), "bytes")

    # 6. Hero render
    html = engine.render('hero.html', {'title': 'SoyMutDB', 'subtitle': 'Soybean Mutant Database'}, widget_name='hero')
    assert 'SoyMutDB' in html
    assert '<script>' not in html
    print("6. Hero render OK:", len(html), "bytes")

    # 7. SRA template render with real SRR30334525 data
    from app.widgets.data_sources.sample_data import SRA_SRR30334525
    ctx = {'run': SRA_SRR30334525, 'run_accession': 'SRR30334525', 'is_fallback': True, 'fetch_error': None}
    sra_html = engine.render('sra_run.html', ctx, widget_name='sra_run')
    assert 'SRR30334525' in sra_html
    assert 'Zea mays' in sra_html
    assert 'RNA-Seq' in sra_html
    assert 'Illumina NovaSeq' in sra_html
    assert 'PRJNA1150623' in sra_html
    assert 'trace.ncbi.nlm.nih.gov' in sra_html
    assert '<script>' not in sra_html
    print("7. SRA run template OK:", len(sra_html), "bytes - contains real NCBI metadata")

    # 8. Search renderer (import directly to avoid sqlalchemy dep)
    search_renderer = importlib.import_module('app.search.renderer')
    render_search_html = search_renderer.render_search_html
    search_models = importlib.import_module('app.search.models')
    ExternalSearchResponse = search_models.ExternalSearchResponse
    SourceResult = search_models.SourceResult
    SearchHit = search_models.SearchHit
    SourceStatus = search_models.SourceStatus
    SearchSource = search_models.SearchSource
    print("8. Search renderer import OK")

    test_hits = [
        SearchHit(
            source=SearchSource.NCBI,
            title='SRR30334525 - Zea mays RNA-Seq',
            url='https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR30334525',
            snippet='Illumina NovaSeq 6000, 385M spots, 116 Gbases, RNA-Seq transcriptomic',
            id='SRR30334525',
        ),
        SearchHit(
            source=SearchSource.UNIPROT,
            title='Glyma.01G123400 - Phytochrome A',
            url='https://www.uniprot.org/uniprotkb/Q2MKB4',
            snippet='Phytochrome A photoreceptor in Glycine max',
            id='Q2MKB4',
        ),
    ]
    src_ncbi = SourceResult(source=SearchSource.NCBI, status=SourceStatus.OK, hits=[test_hits[0]], total=1, elapsed_ms=234.5, error=None)
    src_up = SourceResult(source=SearchSource.UNIPROT, status=SourceStatus.OK, hits=[test_hits[1]], total=1, elapsed_ms=189.2, error=None)
    resp = ExternalSearchResponse(query='GmphyA1', sources=[src_ncbi, src_up], total_hits=2, elapsed_ms=450.0)
    search_html = render_search_html(resp)
    assert 'SRR30334525' in search_html
    assert 'Q2MKB4' in search_html
    assert '<script>' not in search_html
    assert 'ext-search' in search_html
    print("9. Search HTML OK:", len(search_html), "bytes - 2 sources, sanitized")

    # 9. Error source renders degraded
    src_err = SourceResult(source=SearchSource.ENSEMBL, status=SourceStatus.ERROR, hits=[], total=0, elapsed_ms=5000.0, error='Connection timeout')
    resp_deg = ExternalSearchResponse(query='test', sources=[src_err], total_hits=0, elapsed_ms=5000.0)
    deg_html = render_search_html(resp_deg)
    assert 'timeout' in deg_html.lower() or 'unavailable' in deg_html.lower() or 'error' in deg_html.lower()
    print("10. Degraded source renders error message OK")

    # 10. Search circuit breaker module import (may need redis)
    try:
        cb_mod = importlib.import_module('app.search.circuit_breaker')
        CircuitBreaker = cb_mod.CircuitBreaker
        print("11. CircuitBreaker import OK")
    except ImportError as e:
        print(f"11. CircuitBreaker import skipped (needs redis): {e}")

    # 11. Search cache module
    try:
        sc_mod = importlib.import_module('app.search.cache')
        SearchCache = sc_mod.SearchCache
        print("12. SearchCache import OK")
    except ImportError as e:
        print(f"12. SearchCache import skipped (needs redis): {e}")

    print()
    print("=" * 60)
    print("ALL CORE MODULE TESTS PASSED")
    print("=" * 60)

if __name__ == '__main__':
    main()
