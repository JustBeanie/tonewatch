import { expect, test, type Page } from "playwright/test";

async function login(page: Page): Promise<void> {
    await page.goto("/login");
    await page.getByLabel("Password").fill("e2e-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("live call appears and recording plays", async ({ page }) => {
    await login(page);
    const call = page.locator('a[href^="/calls/"]').filter({ hasText: "fixture-radio" }).first();
    await expect(call).toBeVisible({ timeout: 15000 });
    await expect
        .poll(
            async () => {
                const href = await call.getAttribute("href");
                if (!href) return 0;
                return page.evaluate(async (path) => {
                    const response = await fetch(path.replace("/calls/", "/api/calls/"));
                    if (!response.ok) return 0;
                    const detail = (await response.json()) as { recordings?: unknown[] };
                    return detail.recordings?.length ?? 0;
                }, href);
            },
            { timeout: 10000 },
        )
        .toBeGreaterThan(0);
    const recordingResponse = page.waitForResponse((response) => {
        const contentType = response.headers()["content-type"] ?? "";
        return (
            response.url().includes("/api/recordings/") &&
            [200, 206].includes(response.status()) &&
            contentType.startsWith("audio/")
        );
    });
    await call.click();
    const recording = await recordingResponse;
    expect(recording.headers()["content-length"]).toBeTruthy();
    await expect(page.locator("audio")).toBeVisible();
    await expect
        .poll(() =>
            page.locator("audio").evaluate((element) => (element as HTMLAudioElement).readyState),
        )
        .toBeGreaterThanOrEqual(1);
});

test("create tone set through ui", async ({ page }) => {
    await login(page);
    await page.goto("/tonesets/new");
    const name = `E2E tone ${Date.now()}`;
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page).toHaveURL(/\/tonesets$/);
    await expect(page.getByText(name)).toBeVisible();
    const names = await page.evaluate(async () => {
        const response = await fetch("api/tonesets");
        return ((await response.json()) as { name: string }[]).map((item) => item.name);
    });
    expect(names).toContain(name);
});

test("websocket connects", async ({ page }) => {
    let received = 0;
    page.on("websocket", (socket) => {
        socket.on("framereceived", () => {
            received += 1;
        });
    });
    await login(page);
    await expect(page.getByRole("status", { name: "Live connection" })).toHaveText(
        "Live connection: connected",
    );
    await expect.poll(() => received).toBeGreaterThan(0);
});

test("deep link reload renders", async ({ page }) => {
    const notFound: string[] = [];
    page.on("response", (response) => {
        if (response.status() === 404) notFound.push(response.url());
    });
    await page.goto("/tonesets/new");
    await expect(page.getByRole("heading", { name: "Create tone set" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Create tone set" })).toBeVisible();
    expect(notFound).toEqual([]);
});
