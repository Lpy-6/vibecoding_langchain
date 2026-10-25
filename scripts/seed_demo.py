"""
Seed a demo e-commerce knowledge base with multiple file formats.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/seed_demo.py
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.models import Document, IngestTask, KnowledgeBase, User  # noqa: E402
from app.db.session import init_db, sync_session_scope  # noqa: E402
from app.ingest.pipeline import process_document  # noqa: E402
from app.seed import seed_initial_data  # noqa: E402
from app.services.storage import save_bytes, write_text_snapshot  # noqa: E402

DEMO_DIR = settings.data_dir / "demo"

AFTER_SALES_MD = """# 售后服务政策

## 七天无理由退货
自签收之日起 7 天内，商品保持完好、配件与赠品齐全、不影响二次销售的，可申请无理由退货。
定制商品、已激活的数码产品、已拆封的贴身用品、明确标注“不支持七天无理由”的商品除外。
无理由退货的退回运费由买家承担；若订单购买了运费险，可按平台规则理赔。

## 十五天质量问题换货
自签收之日起 15 天内出现非人为性能故障，经检测确认后，可申请同型号同规格换货。
换货商品需保留原包装、配件、发票或电子订单凭证。无同型号库存时可协商退货或补差价换购。

## 保修政策
星辰手机主机享受 1 年保修，电池、充电器等附件享受 6 个月保修；星光平板主机保修 1 年。
人为损坏、进水、私自拆修、非官方渠道维修不在保修范围内。
保修期内维修免收工时费和零件费，保修期外按官方报价收取费用。

## 退款时效
退货验收通过后，退款将在 1-3 个工作日内原路退回：
微信/支付宝通常实时到账；银行卡 1-3 个工作日；花呗分期按分期账单冲抵。
运费、优惠券按实际支付金额结算，已使用的优惠券一般不予退回。

## 售后申请方式
在“我的订单”中选择对应订单，点击“申请售后”，选择退货、换货或维修，上传问题照片并填写描述。
客服将在 24 小时内审核；寄回商品后请在售后页面填写物流单号。
"""

PRODUCT_FAQ_MD = """# 星辰系列手机常见问题

## 星辰 X1 Pro 的屏幕和电池怎么样？
星辰 X1 Pro 配备 6.78 英寸 2K 分辨率 OLED 屏幕，支持 120Hz 自适应刷新率，峰值亮度 3000nit。
电池容量为 5000mAh，支持 80W 有线快充和 50W 无线快充，官方实测 35 分钟可充至 100%。

## 星辰 X1 Pro 的影像配置如何？
后置三摄：5000 万像素主摄（OIS 光学防抖）+ 5000 万像素超广角 + 6400 万像素潜望长焦，支持 3.5 倍光学变焦。
前置 3200 万像素镜头，支持 4K 视频录制。夜景模式支持手持长曝光与 AI 降噪。

## 星辰 X1 和 X1 Pro 有什么区别？
星辰 X1 采用天玑 9300 芯片，6.67 英寸 1.5K 120Hz 屏幕，5500mAh 电池 + 67W 快充，售价 3299 元起。
X1 Pro 采用骁龙 8 Gen3 芯片，2K 屏幕、80W 有线 + 50W 无线充电、潜望长焦，售价 4299 元起。
两者均支持 5G、NFC、红外遥控和 IP68 防尘防水。

## 星辰 X1 Lite 适合什么人群？
星辰 X1 Lite 售价 1999 元起，搭载骁龙 7+ Gen2，6.55 英寸 1080P 120Hz 屏幕，5000mAh 电池 + 45W 快充。
适合日常社交、视频和轻度游戏用户，支持双卡双待和 1TB 存储扩展。

## 手机支持哪些网络和功能？
星辰 X1 系列均支持 5G 双卡双待、Wi-Fi 6、蓝牙 5.3、NFC 和红外遥控。
X1 Pro 支持 IP68 防尘防水；X1 与 X1 Lite 支持 IP54 生活防泼溅。

## 包装清单包含什么？
手机主机 ×1、80W 或 67W 充电器 ×1（按型号）、数据线 ×1、取卡针 ×1、透明保护壳 ×1、快速入门指南 ×1。
耳机、保护膜等赠品以订单页面显示为准。

## 是否支持以旧换新？
支持。下单时选择“以旧换新”，填写旧机型号与成色，系统会给出预估抵扣金额。
旧机由官方合作商回收检测，检测结果与描述一致则按预估金额抵扣；差异较大时可选择取消换新。
"""

BUYING_GUIDE_DOCX = [
    ("购买指南", 0),
    ("支付方式", 1),
    ("支持微信支付、支付宝、银联银行卡、花呗分期以及信用卡分期。", 0),
    ("花呗分期支持 3 期、6 期、12 期，部分商品享免息活动，具体以结算页为准。", 0),
    ("发票说明", 1),
    ("下单时可选择电子普通发票或增值税专用发票；电子发票在订单完成后发送至预留邮箱。", 0),
    ("发票内容默认为商品明细，订单完成后 30 天内可在订单详情中申请换开。", 0),
    ("配送与发货", 1),
    ("现货商品在付款后 48 小时内发货，默认使用顺丰或京东物流，偏远地区可能延迟。", 0),
    ("大家电与平板等大件商品提供送货上门服务，配送前会有客服电话预约。", 0),
    ("优惠与价保", 1),
    ("下单后 15 天内，若同一商品在官方渠道降价，可申请价格保护，退还差价。", 0),
    ("优惠券、满减、赠品活动不可叠加使用的情况以活动规则为准。", 0),
]

PROMO_ROWS = [
    ["活动名称", "适用商品", "优惠内容", "开始时间", "结束时间", "备注"],
    ["双十一抢先购", "星辰 X1 Pro", "满 4000 减 300", "2026-10-20", "2026-11-11", "与店铺券可叠加"],
    ["以旧换新补贴", "星辰 X1 系列", "旧机额外补贴 200 元", "2026-10-01", "2026-12-31", "需官方回收检测"],
    ["平板开学季", "星光平板 P11", "赠键盘保护套", "2026-08-15", "2026-09-30", "赠品数量有限"],
    ["耳机限时优惠", "声悦 Air", "直降 100 元", "2026-10-24", "2026-10-31", "每人限购 2 件"],
    ["免息分期", "全系手机", "12 期免息", "2026-10-01", "2026-11-15", "指定银行信用卡"],
]

POLICY_PDF_PAGES = [
    """退换货政策（一）

一、七天无理由退货
自签收之日起 7 天内，商品完好、配件齐全、不影响二次销售的，可申请无理由退货。
定制商品、已激活数码产品、拆封贴身用品除外。无理由退货运费由买家承担。

二、十五天质量问题换货
签收后 15 天内出现非人为性能故障，经检测确认可换货。需保留包装、配件和订单凭证。

三、申请入口
我的订单 - 申请售后 - 选择退货/换货/维修 - 上传照片 - 提交审核。
客服将在 24 小时内响应。""",
    """退换货政策（二）

四、退款时效
退货验收通过后 1-3 个工作日原路退款。微信/支付宝通常实时到账，银行卡 1-3 个工作日。

五、运费说明
质量问题由商家承担往返运费；无理由退货由买家承担退回运费，运费险按平台规则理赔。

六、保修说明
星辰手机主机保修 1 年，电池与充电器保修 6 个月；星光平板主机保修 1 年。
人为损坏、进水、私自拆修不在保修范围。

七、客服电话
官方客服热线 400-800-1234，服务时间每天 9:00-21:00。""",
]

PRODUCT_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>星辰 X1 Pro 商品详情</title></head>
<body>
<h1>星辰 X1 Pro 旗舰影像手机</h1>
<p>星辰 X1 Pro 采用骁龙 8 Gen3 旗舰芯片，配备 6.78 英寸 2K 120Hz OLED 屏幕，峰值亮度 3000nit。</p>
<p>内置 5000mAh 电池，支持 80W 有线快充与 50W 无线快充，35 分钟可充至 100%。</p>
<p>后置 5000 万像素 OIS 主摄、5000 万像素超广角与 6400 万像素潜望长焦，支持 3.5 倍光学变焦。</p>
<p>提供 12GB+256GB 与 16GB+512GB 两个版本，官方售价分别为 4299 元和 4799 元。</p>
<p>支持 IP68 防尘防水、NFC、红外遥控与双卡双待 5G。整机保修 1 年，支持七天无理由退货。</p>
<p>购买即赠透明保护壳，晒单评价可获赠 50 元优惠券，具体以活动页面为准。</p>
</body></html>"""


def _write_demo_files() -> dict[str, tuple[Path, str, str]]:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    files: dict[str, tuple[Path, str, str]] = {}

    path = DEMO_DIR / "售后服务政策.md"
    path.write_text(AFTER_SALES_MD, encoding="utf-8")
    files["售后服务政策"] = (path, "file", "text/markdown")

    path = DEMO_DIR / "商品常见问题.md"
    path.write_text(PRODUCT_FAQ_MD, encoding="utf-8")
    files["星辰手机常见问题"] = (path, "file", "text/markdown")

    from docx import Document as DocxDocument

    docx_path = DEMO_DIR / "购买指南.docx"
    doc = DocxDocument()
    for text, level in BUYING_GUIDE_DOCX:
        if level == 0 and not doc.paragraphs:
            doc.add_paragraph(text)
        elif level == 1:
            doc.add_heading(text, level=1)
        else:
            doc.add_paragraph(text)
    doc.save(docx_path)
    files["购买指南"] = (docx_path, "file", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    from openpyxl import Workbook

    xlsx_path = DEMO_DIR / "促销活动.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "促销活动"
    for row in PROMO_ROWS:
        ws.append(row)
    ws2 = wb.create_sheet("在售商品")
    ws2.append(["商品名称", "型号", "价格", "芯片", "屏幕", "电池", "快充", "库存"])
    ws2.append(["星辰 X1 Pro", "X1 Pro", 4299, "骁龙 8 Gen3", "6.78英寸 2K 120Hz", "5000mAh", "80W", 320])
    ws2.append(["星辰 X1", "X1", 3299, "天玑 9300", "6.67英寸 1.5K 120Hz", "5500mAh", "67W", 540])
    ws2.append(["星辰 X1 Lite", "X1 Lite", 1999, "骁龙 7+ Gen2", "6.55英寸 1080P 120Hz", "5000mAh", "45W", 860])
    ws2.append(["星光平板 P11", "P11", 2199, "天玑 8300", "11英寸 2.5K 144Hz", "8000mAh", "33W", 210])
    ws2.append(["声悦 Air 耳机", "Air", 499, "—", "—", "—", "—", 1200])
    wb.save(xlsx_path)
    files["促销活动与在售商品"] = (xlsx_path, "file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    import fitz

    pdf_path = DEMO_DIR / "退换货政策.pdf"
    pdf = fitz.open()
    for text in POLICY_PDF_PAGES:
        page = pdf.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontname="china-s", fontsize=11, lineheight=1.6)
    pdf.save(pdf_path)
    pdf.close()
    files["退换货政策（PDF）"] = (pdf_path, "file", "application/pdf")

    html_path = DEMO_DIR / "星辰X1Pro商品详情.html"
    html_path.write_text(PRODUCT_HTML, encoding="utf-8")
    files["星辰 X1 Pro 商品详情页"] = (html_path, "url", "text/html")

    return files


def _add_document(kb_id: str, admin_id: str, title: str, path: Path, source_type: str, mime: str) -> None:
    data = path.read_bytes()
    content_hash = hashlib.sha256(data).hexdigest()
    with sync_session_scope() as session:
        existing = session.scalar(
            select(Document.id).where(
                Document.kb_id == kb_id,
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
        if existing:
            print(f"  跳过重复文档：{title}")
            return
        if source_type == "url":
            html = data.decode("utf-8")
            stored, _ = write_text_snapshot(html, ".html")
            storage_path = str(stored)
            source_url = "https://demo.local/products/xingchen-x1-pro"
            doc = Document(
                kb_id=kb_id,
                title=title,
                source_type="url",
                mime_type=mime,
                size_bytes=len(data),
                storage_path=storage_path,
                source_url=source_url,
                content_hash=content_hash,
                status="pending",
                created_by=admin_id,
                parser_meta={"custom_title": True},
            )
        else:
            stored, _ = save_bytes(data, path.name)
            storage_path = str(stored)
            doc = Document(
                kb_id=kb_id,
                title=title,
                source_type="image" if mime.startswith("image/") else "file",
                original_filename=path.name,
                mime_type=mime,
                size_bytes=len(data),
                storage_path=storage_path,
                content_hash=content_hash,
                status="pending",
                created_by=admin_id,
            )
        session.add(doc)
        session.flush()
        task = IngestTask(document_id=doc.id, kb_id=kb_id, task_type="ingest", max_attempts=3)
        session.add(task)
        session.flush()
        doc_id, task_id = doc.id, task.id
    print(f"  解析：{title} ...", end="", flush=True)
    process_document(doc_id, task_id)
    print(" 完成")


def main() -> None:
    asyncio.run(init_db())
    asyncio.run(seed_initial_data())
    files = _write_demo_files()

    with sync_session_scope() as session:
        admin = session.scalar(select(User).where(User.username == settings.admin_username))
        kb = session.scalar(select(KnowledgeBase).where(KnowledgeBase.name == "商品知识库"))
        if not kb:
            kb = KnowledgeBase(
                name="商品知识库",
                description="电商商品资料、参数与售后政策示例知识库",
                is_public=True,
                created_by=admin.id if admin else None,
            )
            session.add(kb)
            session.flush()
        kb_id = kb.id
        admin_id = admin.id if admin else ""

    print(f"知识库：{kb_id}")
    for title, (path, source_type, mime) in files.items():
        try:
            _add_document(kb_id, admin_id, title, path, source_type, mime)
        except Exception as exc:  # noqa: BLE001
            print(f" 失败：{title}: {exc}")

    with sync_session_scope() as session:
        kb = session.get(KnowledgeBase, kb_id)
        print("\n完成。")
        print(f"  文档数：{kb.doc_count}，子块数：{kb.chunk_count}，版本：v{kb.version}")
        print(f"  当前模式：{settings.effective_llm_mode}")
        print(f"  管理员：{settings.admin_username} / {settings.admin_password}")
        print("  演示用户：demo / demo123")
        print("\n启动后端：backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8000")
        print("启动前端：cd frontend && npm run dev")


if __name__ == "__main__":
    main()
