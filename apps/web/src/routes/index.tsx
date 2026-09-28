import { createFileRoute } from "@tanstack/react-router";
import { AntdHome } from "../components/home/antd-home";

export const Route = createFileRoute("/")({
  component: AntdHome,
});
