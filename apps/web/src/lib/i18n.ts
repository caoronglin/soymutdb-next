/**
 * i18n bootstrap — initializes i18next with the detected language and exposes
 * a small hook wrapper for language switching.
 */
import { initI18n, setLanguage, detectLanguage, type SupportedLanguage } from "@soymutdb/i18n";
import i18n from "@soymutdb/i18n";
import { useTranslation } from "react-i18next";

let initialized = false;

/**
 * App-level translation keys that are not part of the shared
 * @soymutdb/i18n package resources (the package is shared/read-only for this
 * task, so new portal-only strings are merged in at runtime instead).
 */
const EXTRA_RESOURCES: Record<string, Record<string, Record<string, string>>> = {
  en: {
    browser: {
      back: "Back",
      stillLoading: "Still loading…",
      stillLoadingDesc:
        "The JBrowse 2 genome browser at {{url}} is taking longer than expected. You can keep waiting, retry, or open it in a new tab.",
      retry: "Retry",
      openInNewTab: "Open in new tab",
      loadError: "The genome browser could not be loaded.",
      loadErrorDetail:
        "The JBrowse 2 service at {{url}} could not be reached. This may be a temporary connectivity issue or the service may not be deployed yet.",
    },
  },
  zh: {
    browser: {
      back: "返回",
      stillLoading: "仍在加载…",
      stillLoadingDesc:
        "位于 {{url}} 的 JBrowse 2 基因组浏览器响应时间较长。您可以继续等待、重试，或在新标签页中打开。",
      retry: "重试",
      openInNewTab: "在新标签页中打开",
      loadError: "无法加载基因组浏览器。",
      loadErrorDetail:
        "无法连接到位于 {{url}} 的 JBrowse 2 服务。这可能是暂时性网络问题，或该服务尚未部署。",
    },
  },
};

/**
 * Wave 3-C portal-only strings for the Tools hub (nav label + tool pages).
 * Merged with `deep: true` so the shared `nav` bundle is extended, not
 * replaced.
 */
const TOOLS_RESOURCES: Record<string, Record<string, unknown>> = {
  en: {
    nav: {
      tools: "Tools",
    },
    tools: {
      title: "Analysis Tools",
      subtitle: "Sequence extraction, functional enrichment and expression-pattern analysis",
      open: "Open tool",
      note: "For homology search, use",
      seqfetch: {
        title: "SeqFetch",
        cardDesc: "Batch-extract FASTA sequences for up to 200 gene IDs, or pull a single genomic interval from an assembly.",
        subtitle: "Extract genomic sequences by gene list or interval",
        status: "Sequence extraction",
        formTitle: "Extraction parameters",
        formDesc: "Choose one of the two mutually exclusive modes",
        modeGenes: "Gene list",
        modeRegion: "Region",
        genesLabel: "Gene IDs",
        genesPlaceholder: "One gene ID per line — e.g.\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "Up to 200 gene IDs, one per line (commas/spaces also accepted).",
        errorGenesEmpty: "Enter at least one gene ID",
        errorGenesMax: "Up to 200 gene IDs per request",
        assemblyLabel: "Assembly",
        assemblyPlaceholder: "Select an assembly",
        default: "default",
        chromosomeLabel: "Chromosome",
        startLabel: "Start (1-based)",
        endLabel: "End",
        errorAssembly: "Select an assembly",
        errorChromosome: "Enter a chromosome",
        errorCoord: "Enter a valid positive integer",
        regionHint: "Extracts {{region}} (1-based, inclusive).",
        submit: "Fetch sequences",
        resultTitle: "FASTA result",
        countLabel: "{{count}} sequences",
        truncated: "delivered as file",
        resultDesc: "Monospace FASTA preview (first 120 lines shown)",
        previewTruncated: "Preview truncated — {{shown}} of {{total}} lines shown",
        largeTitle: "Large result",
        largeDesc: "The FASTA exceeds the inline size cap and was delivered as a file.",
        download: "Download FASTA",
        downloadFasta: "Download FASTA file",
        missingTitle: "Not found in the database",
        emptyTitle: "No result yet",
        emptyDesc: "Submit a gene list or region to fetch sequences.",
        errorTitle: "Fetch failed",
        toastDone: "Sequences fetched",
        toastDoneDesc: "{{count}} sequences extracted",
        toastFailed: "Fetch failed",
      },
      enrichment: {
        title: "Enrichment",
        cardDesc: "GO/KEGG over-representation test with Benjamini-Hochberg correction for a gene list.",
        subtitle: "GO / KEGG functional enrichment analysis",
        status: "Functional enrichment",
        formTitle: "Analysis parameters",
        formDesc: "Hypergeometric test against the full annotated gene set",
        genesLabel: "Gene IDs",
        genesPlaceholder: "One gene ID per line — e.g.\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "Up to 500 gene IDs, one per line.",
        errorGenesEmpty: "Enter at least one gene ID",
        errorGenesMax: "Up to 500 gene IDs per request",
        ontologyLabel: "Ontology",
        pLabel: "P-value threshold",
        errorP: "Threshold must be between 0 and 1",
        submit: "Run enrichment",
        summaryTitle: "Analysis summary",
        summaryDesc: "{{input}} input genes over a background of {{background}} annotated genes",
        termsBadge: "{{count}} enriched terms",
        resultsTitle: "Enriched terms",
        resultsDesc: "Sorted by adjusted p-value (q), ascending",
        colTerm: "Term",
        colP: "p-value",
        colQ: "q-value",
        colGenes: "Genes",
        colMembers: "Member genes",
        noTermsTitle: "No enriched terms",
        noTermsDesc: "No term passed the threshold. The annotation data may not be imported yet — please contact the database administrators if this persists.",
        emptyTitle: "No result yet",
        emptyDesc: "Submit a gene list to run the enrichment test.",
        errorTitle: "Enrichment failed",
        toastDone: "Enrichment complete",
        toastDoneDesc: "{{count}} enriched terms",
        toastFailed: "Enrichment failed",
      },
      exppattern: {
        title: "Expression Pattern",
        cardDesc: "Gene × condition expression matrix with optional z-scoring and row clustering, as heatmap and table.",
        subtitle: "Expression matrix, clustering and heatmap",
        status: "Expression pattern",
        formTitle: "Analysis parameters",
        formDesc: "Up to 50 genes; rows are z-scored by default",
        genesLabel: "Gene IDs",
        genesPlaceholder: "One gene ID per line — e.g.\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "Up to 50 gene IDs, one per line.",
        errorGenesEmpty: "Enter at least one gene ID",
        errorGenesMax: "Up to 50 gene IDs per request",
        scaleLabel: "Row scaling",
        scaleZscore: "Z-score (default)",
        scaleNone: "Raw FPKM",
        clusterLabel: "Cluster rows",
        submit: "Build matrix",
        summaryTitle: "Matrix summary",
        summaryDesc: "{{genes}} genes × {{conds}} conditions",
        clusteringBadge: "clustering: {{method}}",
        largeBadge: "large matrix",
        missingTitle: "{{count}} gene(s) without expression data",
        heatmapTitle: "Expression heatmap",
        heatmapDesc: "Missing values are left blank",
        heatmapAria: "Expression pattern heatmap",
        matrixTitle: "Expression matrix",
        matrixDesc: "Scroll horizontally for all conditions",
        geneCol: "Gene",
        noDataTitle: "No expression data",
        noDataDesc: "None of the requested genes have expression records.",
        emptyTitle: "No result yet",
        emptyDesc: "Submit a gene list to build the expression matrix.",
        errorTitle: "Analysis failed",
        largeHint: "This matrix is large — heatmap labels may be dense; the full matrix is available in the table below.",
        toastDone: "Matrix ready",
        toastDoneDesc: "{{genes}} genes × {{conds}} conditions",
        toastFailed: "Analysis failed",
      },
    },
  },
  zh: {
    nav: {
      tools: "工具",
    },
    tools: {
      title: "分析工具",
      subtitle: "序列提取、功能富集与表达模式分析",
      open: "打开工具",
      note: "如需同源比对，请使用",
      seqfetch: {
        title: "SeqFetch",
        cardDesc: "批量提取至多 200 个基因 ID 的 FASTA 序列，或按组装从基因组区间提取单条序列。",
        subtitle: "按基因列表或区间提取基因组序列",
        status: "序列提取",
        formTitle: "提取参数",
        formDesc: "两种模式互斥，请选择其一",
        modeGenes: "基因列表",
        modeRegion: "区间",
        genesLabel: "基因 ID",
        genesPlaceholder: "每行一个基因 ID，例如：\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "最多 200 个基因 ID，每行一个（也接受逗号或空格分隔）。",
        errorGenesEmpty: "请至少输入一个基因 ID",
        errorGenesMax: "每次请求最多 200 个基因 ID",
        assemblyLabel: "组装",
        assemblyPlaceholder: "请选择组装",
        default: "默认",
        chromosomeLabel: "染色体",
        startLabel: "起始（1-based）",
        endLabel: "终止",
        errorAssembly: "请选择组装",
        errorChromosome: "请输入染色体",
        errorCoord: "请输入有效的正整数",
        regionHint: "提取区间 {{region}}（1-based，闭区间）。",
        submit: "提取序列",
        resultTitle: "FASTA 结果",
        countLabel: "{{count}} 条序列",
        truncated: "以文件形式交付",
        resultDesc: "等宽字体 FASTA 预览（仅显示前 120 行）",
        previewTruncated: "预览已截断 — 共 {{total}} 行，仅显示前 {{shown}} 行",
        largeTitle: "结果较大",
        largeDesc: "FASTA 超过内联大小上限，已以文件形式交付。",
        download: "下载 FASTA",
        downloadFasta: "下载 FASTA 文件",
        missingTitle: "数据库中未找到",
        emptyTitle: "暂无结果",
        emptyDesc: "提交基因列表或区间以提取序列。",
        errorTitle: "提取失败",
        toastDone: "序列提取完成",
        toastDoneDesc: "已提取 {{count}} 条序列",
        toastFailed: "提取失败",
      },
      enrichment: {
        title: "Enrichment",
        cardDesc: "基于 Benjamini-Hochberg 校正的 GO/KEGG 超几何富集检验。",
        subtitle: "GO / KEGG 功能富集分析",
        status: "功能富集",
        formTitle: "分析参数",
        formDesc: "以全部已注释基因为背景的超几何检验",
        genesLabel: "基因 ID",
        genesPlaceholder: "每行一个基因 ID，例如：\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "最多 500 个基因 ID，每行一个。",
        errorGenesEmpty: "请至少输入一个基因 ID",
        errorGenesMax: "每次请求最多 500 个基因 ID",
        ontologyLabel: "本体",
        pLabel: "P 值阈值",
        errorP: "阈值必须在 0 到 1 之间",
        submit: "运行富集分析",
        summaryTitle: "分析摘要",
        summaryDesc: "{{input}} 个输入基因，背景为 {{background}} 个已注释基因",
        termsBadge: "{{count}} 个富集条目",
        resultsTitle: "富集条目",
        resultsDesc: "按校正后 P 值（q）升序排列",
        colTerm: "条目",
        colP: "P 值",
        colQ: "Q 值",
        colGenes: "基因数",
        colMembers: "成员基因",
        noTermsTitle: "未发现富集条目",
        noTermsDesc: "没有条目通过阈值。注释数据可能尚未导入——若持续如此，请联系数据库管理员。",
        emptyTitle: "暂无结果",
        emptyDesc: "提交基因列表以运行富集检验。",
        errorTitle: "富集分析失败",
        toastDone: "富集分析完成",
        toastDoneDesc: "发现 {{count}} 个富集条目",
        toastFailed: "富集分析失败",
      },
      exppattern: {
        title: "Expression Pattern",
        cardDesc: "基因 × 条件表达矩阵，支持 Z-score 标准化与行聚类，以热图和表格呈现。",
        subtitle: "表达矩阵、聚类与热图",
        status: "表达模式",
        formTitle: "分析参数",
        formDesc: "最多 50 个基因；默认按行 Z-score 标准化",
        genesLabel: "基因 ID",
        genesPlaceholder: "每行一个基因 ID，例如：\nGlyma.01G000100\nGlyma.01G000200",
        genesHint: "最多 50 个基因 ID，每行一个。",
        errorGenesEmpty: "请至少输入一个基因 ID",
        errorGenesMax: "每次请求最多 50 个基因 ID",
        scaleLabel: "行标准化",
        scaleZscore: "Z-score（默认）",
        scaleNone: "原始 FPKM",
        clusterLabel: "行聚类",
        submit: "构建矩阵",
        summaryTitle: "矩阵摘要",
        summaryDesc: "{{genes}} 个基因 × {{conds}} 个条件",
        clusteringBadge: "聚类方式：{{method}}",
        largeBadge: "大矩阵",
        missingTitle: "{{count}} 个基因无表达数据",
        heatmapTitle: "表达热图",
        heatmapDesc: "缺失值以空白显示",
        heatmapAria: "表达模式热图",
        matrixTitle: "表达矩阵",
        matrixDesc: "横向滚动查看全部条件",
        geneCol: "基因",
        noDataTitle: "暂无表达数据",
        noDataDesc: "请求的基因均无表达记录。",
        emptyTitle: "暂无结果",
        emptyDesc: "提交基因列表以构建表达矩阵。",
        errorTitle: "分析失败",
        largeHint: "该矩阵较大——热图标签可能较密；完整矩阵见下方表格。",
        toastDone: "矩阵构建完成",
        toastDoneDesc: "{{genes}} 个基因 × {{conds}} 个条件",
        toastFailed: "分析失败",
      },
    },
  },
};

export function initI18nOnce(): void {
    if (initialized) return;
    initI18n(detectLanguage());
    for (const [lng, bundle] of Object.entries(EXTRA_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle, true);
        i18n.addResourceBundle(lng, "translation", bundle, true);
    }
    for (const [lng, bundle] of Object.entries(TOOLS_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle, true);
        i18n.addResourceBundle(lng, "translation", bundle, true);
    }
    initialized = true;
}

export function useI18n() {
    const { t, i18n } = useTranslation();
    const change = (lang: SupportedLanguage) => setLanguage(lang);
    return { t, i18n, changeLanguage: change, currentLanguage: i18n.language as SupportedLanguage };
}

export { detectLanguage, type SupportedLanguage };
