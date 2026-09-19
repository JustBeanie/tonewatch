import { describe, expect, it, vi } from "vitest";
import { download } from "./download";

describe("admin downloads", () => {
    it("downloads the response using its filename", async () => {
        const click = vi.fn();
        vi.stubGlobal(
            "fetch",
            vi.fn(
                async () =>
                    new Response("file", {
                        headers: { "Content-Disposition": 'attachment; filename="config.yaml"' },
                    }),
            ),
        );
        vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:download");
        vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
        vi.spyOn(document, "createElement").mockReturnValue({
            click,
            href: "",
            download: "",
        } as unknown as HTMLAnchorElement);
        await download("admin/config/export");
        expect(click).toHaveBeenCalled();
    });

    it("surfaces a readable failed download", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(
                async () =>
                    new Response(JSON.stringify({ detail: "support bundle rate limit" }), {
                        status: 429,
                    }),
            ),
        );
        await expect(download("admin/support-bundle", { method: "POST" })).rejects.toMatchObject({
            status: 429,
        });
    });
});
