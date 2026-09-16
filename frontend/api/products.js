/* GET /api/products?style=고프코어&limit=16&offset=0
 *
 * 상품 목록 — 지금 RDS 에 **실제로 들어 있는** 데이터다.
 * 2026-09-02 실측으로 commerce.product 3,375건 · product_source 3,375건.
 * 지표(analysis.*)가 비어 있어도 이 화면은 실값으로 보여 줄 수 있다.
 *
 * 가격은 `snapshot.product_source_snapshot` 의 **가장 최근 한 줄**을 붙인다.
 * 스냅샷이 없는 상품은 가격 자리를 null 로 두고 이유를 함께 보낸다 —
 * 0원으로 채우면 화면이 "공짜"라고 말하게 된다.
 */

import { q, viaBackend } from './_lib/db.js';
import { ok, empty, failed } from './_lib/reply.js';

export default async function handler(req, res) {
  // Django API 가 설정돼 있으면 그쪽이 먼저다 (RDS 를 열지 않아도 된다).
  const relayed = await viaBackend('/products' + (req.url.includes('?') ? '?' + req.url.split('?')[1] : ''));
  if (relayed) {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    return res.end(JSON.stringify(relayed));
  }

  const url = new URL(req.url, 'http://x');
  const kw = (url.searchParams.get('q') || '').trim();
  const brand = (url.searchParams.get('brand') || '').trim();
  const style = (url.searchParams.get('style') || '').trim();
  const limit = Math.min(200, Math.max(1, Number(url.searchParams.get('limit') || 40)));
  const offset = Math.min(1000000, Math.max(0, Number(url.searchParams.get('offset') || 0)));

  const where = ["ps.status = 'ACTIVE'"];
  const args = [];
  if (kw) {
    args.push(`%${kw}%`);
    where.push(`(p.canonical_name ILIKE $${args.length} OR ps.source_name ILIKE $${args.length})`);
  }
  if (brand) {
    args.push(brand);
    where.push(`(b.name = $${args.length} OR LOWER(b.english_name) = LOWER($${args.length})
                 OR bs.name = $${args.length} OR LOWER(bs.english_name) = LOWER($${args.length}))`);
  }
  if (style) {
    args.push(style);
    where.push(`(
      direct_style.canonical_name = $${args.length}
      OR EXISTS (
        SELECT 1
          FROM commerce.product_term pt
          JOIN dictionary.dictionary_term tagged_style ON tagged_style.id = pt.term_id
         WHERE pt.product_source_id = ps.id
           AND tagged_style.term_type = 'STYLE'
           AND tagged_style.canonical_name = $${args.length}
      )
    )`);
  }
  args.push(limit + 1);
  const limitArg = args.length;
  args.push(offset);
  const offsetArg = args.length;

  const r = await q(
    `SELECT p.id, ps.id AS product_source_id,
            COALESCE(p.canonical_name, ps.source_name) AS name,
            COALESCE(b.name, bs.name) AS brand, b.english_name AS brand_en,
            ps.source_product_id, ps.product_url, ps.thumbnail_url, ps.market_type,
            cs.source_category_name,
            src.code AS source_code, src.name AS source_name,
            s.list_price, s.sale_price, s.discount_rate, s.stock_status, s.observed_at
       FROM commerce.product_source ps
       LEFT JOIN commerce.product p ON p.id = ps.product_id
       LEFT JOIN dictionary.brand b ON b.id = p.brand_id
       LEFT JOIN dictionary.brand_source bs ON bs.id = ps.source_brand_id
       LEFT JOIN dictionary.category_source cs ON cs.id = ps.source_category_id
       LEFT JOIN dictionary.dictionary_term direct_style ON direct_style.id = p.style_id
       LEFT JOIN collection.source src ON src.id = ps.source_id
       LEFT JOIN LATERAL (
            SELECT list_price, sale_price, discount_rate, stock_status, observed_at
              FROM snapshot.product_source_snapshot sn
             WHERE sn.product_source_id = ps.id
             ORDER BY observed_at DESC LIMIT 1) s ON true
      WHERE ${where.join(' AND ')}
      ORDER BY ps.last_seen_at DESC NULLS LAST, ps.id DESC
      LIMIT $${limitArg} OFFSET $${offsetArg}`,
    args,
  );

  if (!r.ok) return failed(res, `AWS RDS 에 연결하지 못했습니다 (${r.code}).`, { detail: r.error });
  if (!r.rows.length) {
    return empty(
      res,
      kw || brand || style
        ? `조건에 맞는 상품이 없습니다 (검색어 ‘${kw || brand || style}’).`
        : 'AWS RDS 의 commerce.product 가 비어 있습니다.',
    );
  }

  const hasMore = r.rows.length > limit;
  const items = r.rows.slice(0, limit).map((x) => ({
    id: x.id || x.product_source_id,
    product_source_id: x.product_source_id,
    name: x.name || '(이름 없음)',
    brand: x.brand || null,
    brand_en: x.brand_en || null,
    source: x.source_code || null,
    source_label: x.source_name || null,
    market: x.market_type || null,
    url: x.product_url || null,
    image: x.thumbnail_url || null,
    category: x.source_category_name || null,
    price: {
      list: numOrNull(x.list_price),
      sale: numOrNull(x.sale_price),
      discount: numOrNull(x.discount_rate),
      stock: x.stock_status || null,
      as_of: x.observed_at ? String(x.observed_at).slice(0, 10) : null,
      // 스냅샷이 없으면 0 으로 채우지 않고 이유를 남긴다.
      unavailable: x.observed_at ? null : '이 상품은 아직 가격 스냅샷이 없습니다.',
    },
  }));

  const 가격없음 = items.filter((i) => i.price.unavailable).length;
  return ok(
    res,
    {
      count: items.length,
      items,
      offset,
      next_offset: offset + items.length,
      has_more: hasMore,
      style: style ? [style] : [],
    },
    가격없음 ? { note: `${가격없음}건은 가격 기록이 아직 없습니다.` } : {},
  );
}

function numOrNull(v) {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
