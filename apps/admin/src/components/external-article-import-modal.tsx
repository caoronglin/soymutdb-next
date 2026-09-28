/**
 * Frontend-only external article preview/import workflow.
 *
 * The API-client exports referenced here are intentionally expected to be
 * supplied by the caller's forthcoming API-client contract update.
 */
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Typography,
} from "../lib/antd";
import {
  CheckOutlined,
  EyeOutlined,
  LinkOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import {
  previewExternalNewsArticle,
  type ExternalArticlePlatform,
  type ExternalArticlePreview,
} from "@soymutdb/api-client";

const PLATFORM_OPTIONS: Array<{ value: ExternalArticlePlatform; label: string }> = [
  { value: "wechat", label: "WeChat" },
  { value: "xmol", label: "X-MOL" },
];

interface ExternalArticleImportFormValues {
  platform: ExternalArticlePlatform;
  source_url: string;
}

export interface ExternalArticleImportModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Receives a reviewed preview; saving and publishing remain caller-owned. */
  onApply: (preview: ExternalArticlePreview) => void;
  disabled?: boolean;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to preview the external article.";
}

/**
 * Fetches an external source preview without saving or publishing anything.
 * The preview body is deliberately displayed as text, never injected as HTML.
 */
export function ExternalArticleImportModal({
  open,
  onOpenChange,
  onApply,
  disabled = false,
}: ExternalArticleImportModalProps) {
  const [form] = Form.useForm<ExternalArticleImportFormValues>();
  const [preview, setPreview] = useState<ExternalArticlePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      form.resetFields();
      setPreview(null);
      setPreviewing(false);
      setError(null);
    }
  }, [form, open]);

  const clearPreview = () => {
    setPreview(null);
    setError(null);
  };

  const handlePreview = async (values: ExternalArticleImportFormValues) => {
    setPreviewing(true);
    setPreview(null);
    setError(null);
    try {
      const result = await previewExternalNewsArticle({
        platform: values.platform,
        source_url: values.source_url.trim(),
      });
      setPreview(result);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setPreviewing(false);
    }
  };

  const handleApply = () => {
    if (!preview || disabled) return;
    onApply(preview);
  };

  return (
    <Modal
      open={open}
      title="Import external article"
      onCancel={() => onOpenChange(false)}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={() => onOpenChange(false)} disabled={previewing}>
            Cancel
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            disabled={!preview || previewing || disabled}
            onClick={handleApply}
          >
            Apply reviewed preview
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        message="Review before saving"
        description="Previewing or applying this source does not create, save, or publish a news article. Review the imported content and make any edits before saving it in the news form."
        style={{ marginBottom: 16 }}
      />

      <Form<ExternalArticleImportFormValues>
        form={form}
        layout="vertical"
        initialValues={{ platform: "wechat", source_url: "" }}
        onFinish={(values) => void handlePreview(values)}
        onValuesChange={clearPreview}
      >
        <Form.Item
          label="Platform"
          name="platform"
          rules={[{ required: true, message: "Choose an external platform." }]}
        >
          <Select options={PLATFORM_OPTIONS} disabled={disabled || previewing} />
        </Form.Item>
        <Form.Item
          label="Article URL"
          name="source_url"
          rules={[
            { required: true, message: "Enter an HTTPS article URL." },
            {
              validator: async (_, value: unknown) => {
                const text = typeof value === "string" ? value.trim() : "";
                if (!text) return;
                try {
                  const url = new URL(text);
                  if (url.protocol !== "https:") {
                    throw new Error("Only HTTPS URLs are allowed.");
                  }
                } catch (reason) {
                  throw reason instanceof Error
                    ? reason
                    : new Error("Enter a valid HTTPS URL.");
                }
              },
            },
          ]}
        >
          <Input
            prefix={<LinkOutlined />}
            placeholder="https://example.com/article"
            autoComplete="url"
            disabled={disabled || previewing}
          />
        </Form.Item>
        <Button
          htmlType="submit"
          icon={previewing ? <LoadingOutlined /> : <EyeOutlined />}
          loading={previewing}
          disabled={disabled}
        >
          Preview article
        </Button>
      </Form>

      {error ? (
        <Alert
          type="error"
          showIcon
          message="Preview failed"
          description={error}
          style={{ marginTop: 16 }}
        />
      ) : null}

      {preview ? (
        <div className="mt-4 space-y-3 rounded-lg border border-border p-4">
          <Typography.Title level={5} className="!mb-0">
            Preview ready
          </Typography.Title>
          <div>
            <Typography.Text type="secondary">Title</Typography.Text>
            <Typography.Paragraph className="!mb-0">{preview.title}</Typography.Paragraph>
          </div>
          <div>
            <Typography.Text type="secondary">Source</Typography.Text>
            <Typography.Paragraph className="!mb-0 break-all">
              {preview.source_url}
            </Typography.Paragraph>
          </div>
          {preview.source_published_at ? (
            <div>
              <Typography.Text type="secondary">Source publication date</Typography.Text>
              <Typography.Paragraph className="!mb-0">
                {preview.source_published_at}
              </Typography.Paragraph>
            </div>
          ) : null}
          <div>
            <Typography.Text type="secondary">Imported body (text preview)</Typography.Text>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-sm">
              {preview.content_html}
            </pre>
          </div>
          {/* The fingerprint is an internal provenance field. The signed preview
              attestation carries it to the save boundary without displaying it. */}
        </div>
      ) : null}
    </Modal>
  );
}

export default ExternalArticleImportModal;
