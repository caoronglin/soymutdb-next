/**
 * AntD 5 试点页（B2 基础）— G1 截图基线对象。
 *
 * 4 个场景（data-testid 供 Playwright 定位，见 tests/e2e/antd-pilot.spec.ts）：
 *   1. pilot-form   — Input + Select（基因 ID / 组装选择）
 *   2. pilot-table  — Table（基因列表，含 Tag 渲染突变类型）
 *   3. pilot-modal  — Modal + Drawer（基因详情弹窗 / 侧栏）
 *   4. pilot-dark   — 暗色切换按钮（局部 ConfigProvider algorithm +
 *                     暗色独立 OKLCH 覆盖，见 lib/antd-theme.ts）
 *
 * 演示「AntD 组件 + Tailwind 文本共存」：页面骨架/排版用 Tailwind 类，
 * 交互组件用 AntD，两者通过 index.css 顶部的 @layer 顺序共处。
 *
 * 注意：本文件不 import @soymutdb/ui（eslint no-restricted-imports 门禁）。
 */
import { createFileRoute } from "@tanstack/react-router";
import * as React from "react";
import {
    Button,
    ConfigProvider,
    Drawer,
    Input,
    Modal,
    Select,
    Table,
    Tag,
    Typography,
    type TableColumnsType,
} from "antd";
import { ExperimentOutlined, MoonOutlined, SunOutlined } from "@ant-design/icons";
import { createAntdTheme } from "../lib/antd-theme";

export const Route = createFileRoute("/antd-pilot")({
    component: AntdPilotComponent,
});

interface GeneRow {
    key: string;
    geneId: string;
    chromosome: string;
    variantType: "SNP" | "InDel" | "SV";
    position: string;
    effect: string;
}

const GENE_ROWS: GeneRow[] = [
    { key: "1", geneId: "Glyma.01G000100", chromosome: "Chr01", variantType: "SNP", position: "3,214,908", effect: "missense" },
    { key: "2", geneId: "Glyma.03G123400", chromosome: "Chr03", variantType: "InDel", position: "38,102,455", effect: "frameshift" },
    { key: "3", geneId: "Glyma.05G067800", chromosome: "Chr05", variantType: "SNP", position: "7,845,120", effect: "synonymous" },
    { key: "4", geneId: "Glyma.07G204500", chromosome: "Chr07", variantType: "SV", position: "44,556,003", effect: "deletion" },
    { key: "5", geneId: "Glyma.10G110200", chromosome: "Chr10", variantType: "SNP", position: "19,204,771", effect: "nonsense" },
];

const VARIANT_COLORS: Record<GeneRow["variantType"], string> = {
    SNP: "green",
    InDel: "orange",
    SV: "purple",
};

const COLUMNS: TableColumnsType<GeneRow> = [
    { title: "Gene ID", dataIndex: "geneId", key: "geneId" },
    { title: "Chromosome", dataIndex: "chromosome", key: "chromosome" },
    {
        title: "Variant type",
        dataIndex: "variantType",
        key: "variantType",
        render: (v: GeneRow["variantType"]) => <Tag color={VARIANT_COLORS[v]}>{v}</Tag>,
    },
    { title: "Position", dataIndex: "position", key: "position" },
    { title: "Effect", dataIndex: "effect", key: "effect" },
];

function AntdPilotComponent() {
    // 场景 4：暗色切换（局部 ConfigProvider，全局主题不受影响）
    const [dark, setDark] = React.useState(false);
    const [geneId, setGeneId] = React.useState("");
    const [assembly, setAssembly] = React.useState("Glyma.Wm82.a2.v1");
    // 场景 3：Modal / Drawer
    const [modalOpen, setModalOpen] = React.useState(false);
    const [drawerOpen, setDrawerOpen] = React.useState(false);

    return (
        <ConfigProvider theme={createAntdTheme({ dark })}>
            <div className="container-prose section-rhythm">
                <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <p className="eyebrow">B2 pilot</p>
                        <h1 className="text-h1">Ant Design 5 试点页</h1>
                        <p className="mt-2 max-w-2xl text-small text-muted-foreground">
                            AntD 组件与 Tailwind 排版共存演示 — G1 截图基线对象。
                            本页所有交互组件来自 antd，骨架样式来自 Tailwind / design 层。
                        </p>
                    </div>
                    <Button
                        data-testid="pilot-dark-toggle"
                        icon={dark ? <SunOutlined /> : <MoonOutlined />}
                        onClick={() => setDark((d) => !d)}
                    >
                        {dark ? "Light mode" : "Dark mode"}
                    </Button>
                </div>

                {/* 场景 1 — 表单 */}
                <section data-testid="pilot-form" className="mb-10 rounded-xl border border-border bg-card p-6">
                    <Typography.Title level={3}>Scenario 1 — Form</Typography.Title>
                    <div className="flex flex-wrap items-end gap-4">
                        <div>
                            <label className="mb-1 block text-small text-muted-foreground" htmlFor="pilot-gene-input">
                                Gene ID
                            </label>
                            <Input
                                id="pilot-gene-input"
                                data-testid="pilot-gene-input"
                                placeholder="e.g. Glyma.01G000100"
                                value={geneId}
                                onChange={(e) => setGeneId(e.target.value)}
                                style={{ width: 280 }}
                            />
                        </div>
                        <div>
                            <label className="mb-1 block text-small text-muted-foreground" htmlFor="pilot-assembly">
                                Assembly
                            </label>
                            <Select
                                id="pilot-assembly"
                                data-testid="pilot-assembly"
                                value={assembly}
                                onChange={setAssembly}
                                style={{ width: 220 }}
                                options={[
                                    { value: "Glyma.Wm82.a2.v1", label: "Glyma.Wm82.a2.v1" },
                                    { value: "Glyma.Wm82.a4.v1", label: "Glyma.Wm82.a4.v1" },
                                ]}
                            />
                        </div>
                        <Button type="primary" icon={<ExperimentOutlined />}>
                            Fetch
                        </Button>
                    </div>
                    <p className="mt-4 text-caption text-muted-foreground">
                        AntD Input/Select + Tailwind 间距/文本类共存。当前输入：{geneId || "—"}
                    </p>
                </section>

                {/* 场景 2 — 表格 */}
                <section data-testid="pilot-table" className="mb-10 rounded-xl border border-border bg-card p-6">
                    <Typography.Title level={3}>Scenario 2 — Table</Typography.Title>
                    <Table<GeneRow> columns={COLUMNS} dataSource={GENE_ROWS} size="middle" pagination={false} />
                </section>

                {/* 场景 3 — 弹窗 */}
                <section data-testid="pilot-modal" className="mb-10 rounded-xl border border-border bg-card p-6">
                    <Typography.Title level={3}>Scenario 3 — Modal / Drawer</Typography.Title>
                    <div className="flex flex-wrap gap-3">
                        <Button data-testid="pilot-modal-open" type="primary" onClick={() => setModalOpen(true)}>
                            Open Modal
                        </Button>
                        <Button data-testid="pilot-drawer-open" onClick={() => setDrawerOpen(true)}>
                            Open Drawer
                        </Button>
                    </div>
                    <p className="mt-4 text-caption text-muted-foreground">
                        Modal/Drawer 经 portal 渲染到 body，仍继承本页局部 ConfigProvider 主题（含暗色）。
                    </p>
                </section>

                <Modal
                    title="Gene detail"
                    open={modalOpen}
                    onOk={() => setModalOpen(false)}
                    onCancel={() => setModalOpen(false)}
                >
                    <p>
                        <Tag color="green">Glyma.01G000100</Tag> — Chr01:3,214,908 (SNP, missense)
                    </p>
                    <p className="text-small text-muted-foreground">示例弹窗：基因详情（占位）。</p>
                </Modal>

                <Drawer title="Gene record" open={drawerOpen} onClose={() => setDrawerOpen(false)}>
                    <p>
                        <Tag color="green">Glyma.05G067800</Tag> — Chr05:7,845,120
                    </p>
                    <p className="text-small">示例侧栏：突变记录详情（占位）。</p>
                </Drawer>
            </div>
        </ConfigProvider>
    );
}
