from __future__ import annotations

from collections import Counter

from django.db import close_old_connections
from django.db.models import Count, Q

from apps.core.models import Brand, ProductSource

from .batch import SOURCE_FILTER, run_product_agent_batch
from .repository import code


def _brand_label(brand):
    for field in ('name', 'canonical_name', 'korean_name', 'english_name'):
        value = getattr(brand, field, None)
        if value:
            return str(value)
    return str(brand)


def _brand_source_queryset(brand_id, *, include_linked=True):
    qs = ProductSource.objects.filter(
        SOURCE_FILTER,
        status='ACTIVE',
        source_brand__brand_id=brand_id,
    ).select_related('source', 'source_brand', 'source_brand__brand')
    if not include_linked:
        qs = qs.filter(product_id__isnull=True)
    return qs


def get_brand_agent_summary(*, brand_id, include_linked=True):
    brand = Brand.objects.get(pk=brand_id)
    qs = _brand_source_queryset(brand_id, include_linked=include_linked)

    source_counts = Counter()
    for source_code, count in qs.values_list('source__code').annotate(count=Count('pk')):
        source_counts[code(source_code)] += count

    return {
        'brand_id': brand.pk,
        'brand_name': _brand_label(brand),
        'total_sources': qs.count(),
        'linked_sources': qs.filter(product_id__isnull=False).count(),
        'unlinked_sources': qs.filter(product_id__isnull=True).count(),
        'source_counts': dict(source_counts),
    }


def run_brand_agent(
    *,
    brand_id,
    apply=False,
    model=None,
    reviewer=None,
    candidate_limit=12,
    include_linked=True,
    chunk_size=50,
    log=print,
    verbose=True,
    continue_on_error=True,
):
    """Run the full Product Agent pipeline for exactly one FEEDIT Brand.

    Processing order is inherited from batch.py:
    MUSINSA -> KREAM -> ZIGZAG -> ABLY -> MUSINSA_USED.

    Every ProductSource is processed by the normal ProductAgentOrchestrator,
    so name/attribute/DictionaryTerm review and MAP/PROMOTE/HOLD all use the
    existing production logic. chunk_size only bounds one internal DB/LLM batch;
    this function keeps consuming the same brand until it is complete.
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError('chunk_size must be a positive integer')

    summary = get_brand_agent_summary(brand_id=brand_id, include_linked=include_linked)
    total = summary['total_sources']

    log('=' * 88)
    log(f"BRAND AGENT | {summary['brand_name']} | BRAND #{brand_id}")
    log('=' * 88)
    log(
        'SOURCE | '
        + ' | '.join(
            f'{name.upper()}={summary["source_counts"].get(name, 0)}'
            for name in ('musinsa', 'kream', 'zigzag', 'ably', 'musinsa_used')
        )
        + f' | TOTAL={total}'
    )
    log(
        f"LINK | linked={summary['linked_sources']} "
        f"unlinked={summary['unlinked_sources']} apply={apply}"
    )

    if total == 0:
        log('BRAND DONE | 처리할 ProductSource 없음')
        return {
            **summary,
            'applied': apply,
            'results': [],
            'errors': [],
            'totals': {},
            'attempted_products': 0,
            'success_products': 0,
            'failed_products': 0,
            'has_more': False,
        }

    cursor = None
    all_results = []
    all_errors = []
    chunk_no = 0

    while True:
        chunk_no += 1
        before = len(all_results) + len(all_errors)
        log(f'\n--- BRAND CHUNK {chunk_no} | progress={before}/{total} ---')

        batch = run_product_agent_batch(
            brand_batch_size=1,
            max_products=chunk_size,
            cursor=cursor,
            brand_ids=[brand_id],
            apply=apply,
            model=model,
            reviewer=reviewer,
            candidate_limit=candidate_limit,
            include_linked=include_linked,
            log=log,
            verbose=verbose,
        )

        all_results.extend(batch['results'])
        all_errors.extend(batch['errors'])
        cursor = batch['next_cursor']
        attempted = len(all_results) + len(all_errors)

        action_counts = Counter(row['action'] for row in all_results)
        log(
            f'BRAND PROGRESS | {attempted}/{total} '
            f'| success={len(all_results)} failed={len(all_errors)} '
            f'| actions={dict(action_counts)}'
        )

        if batch['errors'] and not continue_on_error:
            log('BRAND STOP | 오류 발생으로 중단')
            break
        if not batch['has_more']:
            break
        if attempted == before:
            # Safety against a malformed/non-advancing cursor.
            raise RuntimeError(f'Brand agent cursor did not advance: {cursor}')

        close_old_connections()

    totals = dict(Counter(row['action'] for row in all_results))
    log('\n' + '=' * 88)
    log(
        f"BRAND DONE | {summary['brand_name']} | attempted={len(all_results)+len(all_errors)} "
        f"success={len(all_results)} failed={len(all_errors)} | actions={totals}"
    )
    if all_errors:
        log('FAILED PS | ' + ', '.join(str(row['product_source_id']) for row in all_errors))
    log('=' * 88)

    return {
        **summary,
        'applied': apply,
        'results': all_results,
        'errors': all_errors,
        'failed_product_source_ids': [row['product_source_id'] for row in all_errors],
        'totals': totals,
        'attempted_products': len(all_results) + len(all_errors),
        'success_products': len(all_results),
        'failed_products': len(all_errors),
        'next_cursor': cursor,
        'has_more': False,
    }


def run_brand_agent_batch(
    *,
    brand_ids=None,
    brand_limit=None,
    after_brand_id=0,
    apply=False,
    model=None,
    reviewer=None,
    candidate_limit=12,
    include_linked=True,
    chunk_size=50,
    log=print,
    verbose=True,
    continue_on_error=True,
):
    """Run complete brand-by-brand processing for multiple FEEDIT brands."""
    source_qs = ProductSource.objects.filter(
        SOURCE_FILTER,
        status='ACTIVE',
        source_brand__brand_id__isnull=False,
    )
    if not include_linked:
        source_qs = source_qs.filter(product_id__isnull=True)

    brands = Brand.objects.filter(
        pk__in=source_qs.values('source_brand__brand_id'),
        pk__gt=after_brand_id,
    ).order_by('pk')

    if brand_ids is not None:
        brands = brands.filter(pk__in=list(brand_ids))
    if brand_limit is not None:
        if isinstance(brand_limit, bool) or not isinstance(brand_limit, int) or brand_limit < 1:
            raise ValueError('brand_limit must be a positive integer or None')
        brand_pk_list = list(brands.values_list('pk', flat=True)[:brand_limit])
    else:
        brand_pk_list = list(brands.values_list('pk', flat=True))

    outputs = []
    failed_brands = []
    total_brands = len(brand_pk_list)

    for index, brand_id in enumerate(brand_pk_list, 1):
        log(f'\n\n######## BRAND {index}/{total_brands} | #{brand_id} ########')
        try:
            outputs.append(run_brand_agent(
                brand_id=brand_id,
                apply=apply,
                model=model,
                reviewer=reviewer,
                candidate_limit=candidate_limit,
                include_linked=include_linked,
                chunk_size=chunk_size,
                log=log,
                verbose=verbose,
                continue_on_error=continue_on_error,
            ))
        except Exception as exc:
            failed_brands.append({
                'brand_id': brand_id,
                'error_type': type(exc).__name__,
                'error': str(exc),
            })
            log(f'BRAND FAILED | #{brand_id} | {type(exc).__name__}: {exc}')
            if not continue_on_error:
                raise
        finally:
            close_old_connections()

    actions = Counter()
    attempted = success = failed = 0
    for row in outputs:
        actions.update(row['totals'])
        attempted += row['attempted_products']
        success += row['success_products']
        failed += row['failed_products']

    return {
        'applied': apply,
        'brand_results': outputs,
        'failed_brands': failed_brands,
        'processed_brand_ids': [row['brand_id'] for row in outputs],
        'totals': dict(actions),
        'attempted_products': attempted,
        'success_products': success,
        'failed_products': failed,
        'next_brand_id': brand_pk_list[-1] if brand_pk_list else after_brand_id,
    }
