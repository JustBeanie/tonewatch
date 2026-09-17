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
    await expect(page.getByRole("heading", { name: "Create tone set" })).toBeVisible();
    const name = `E2E tone ${Date.now()}`;
    await page.getByLabel("Name").fill(name);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page).toHaveURL(/\/tonesets$/, { timeout: 15000 });
    await expect(page.getByText(name)).toBeVisible();
    const names = await page.evaluate(async () => {
        const response = await fetch("api/tonesets");
        return ((await response.json()) as { name: string }[]).map((item) => item.name);
    });
    expect(names).toContain(name);
});

test("create Meshtastic target from an existing MQTT target", async ({ page }) => {
    await login(page);
    await page.goto("/alerts");
    await page.getByLabel("Name").fill("E2E MQTT");
    await page.getByLabel("Type").selectOption("mqtt");
    await page.getByRole("button", { name: "Save target" }).click();
    await expect(page.getByText("E2E MQTT")).toBeVisible();

    await page.getByLabel("Name").fill("E2E Meshtastic");
    await page.getByLabel("Type").selectOption("meshtastic");
    await page.getByLabel("Existing MQTT target").selectOption({ label: "E2E MQTT" });
    await page.getByLabel("Channel index").fill("1");
    await page.getByLabel("Template").fill("{agency_short} {toneset}");
    await expect(page.getByText(/\d+ \/ 200 bytes/)).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: "Save target" }).click();
    await expect(page.getByText("E2E Meshtastic")).toBeVisible({ timeout: 10000 });
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

test("live listen starts and releases a file-source listener", async ({ page }) => {
    await login(page);
    await page.goto("/sources");
    const source = page.locator(".card").filter({ hasText: "fixture-radio" }).first();
    await expect(source).toBeVisible();
    const listen = source.getByRole("button", { name: "Listen live" });
    await expect(listen).toBeEnabled();
    await listen.click();
    await expect(source.locator("audio")).toHaveAttribute("src", /live\.mp3/);
    const listenerStatus = source.getByRole("status").filter({ hasText: /listeners?/ });
    await expect(listenerStatus).toContainText("1 listener");
    await source.getByRole("button", { name: "Stop live" }).click();
    await expect(listenerStatus).toContainText("0 listeners");
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

test("agency editor links the fixture and map pulses without external requests", async ({
    page,
}) => {
    test.setTimeout(90000);
    const external: string[] = [];
    let mapOpen = false;
    let resolveEventsSubscribed: (() => void) | undefined;
    const eventsSubscribed = new Promise<void>((resolve) => {
        resolveEventsSubscribed = resolve;
    });
    page.on("websocket", (socket) =>
        socket.on("framereceived", (frame) => {
            const payload = (frame as { payload?: unknown }).payload ?? frame;
            try {
                const message = JSON.parse(String(payload)) as {
                    type?: string;
                    data?: { topics?: unknown };
                };
                if (!mapOpen) return;
                if (
                    message.type === "subscribed" &&
                    Array.isArray(message.data?.topics) &&
                    message.data.topics.includes("events")
                )
                    resolveEventsSubscribed?.();
            } catch {
                // Ignore non-JSON websocket frames.
            }
        }),
    );
    page.on("request", (request) => {
        const url = new URL(request.url());
        if (!["localhost", "127.0.0.1"].includes(url.hostname)) external.push(request.url());
    });
    await login(page);
    await page.goto("/agencies/new");
    await page.getByLabel("ID").fill("fixture-agency");
    await page.getByRole("textbox", { name: "Name", exact: true }).fill("Fixture Agency");
    await page.getByLabel("Short name").fill("FA");
    await page.getByLabel("Latitude").fill("40.1");
    await page.getByLabel("Longitude").fill("-105.2");
    const fixtureTone = page.getByLabel("Fixture page");
    await expect(fixtureTone).toBeVisible();
    await fixtureTone.check();
    await page.getByRole("button", { name: "Save agency" }).click();
    await expect(page).toHaveURL(/\/agencies$/);
    await page.goto("/map");
    mapOpen = true;
    await expect(page.getByTestId("map-marker-fixture-agency")).toBeVisible();
    await page
        .getByRole("region", { name: "Agency list" })
        .getByRole("button", { name: "Fixture Agency" })
        .click();
    await expect(page.getByText("Fixture page")).toBeVisible();
    await eventsSubscribed;
    const trigger = page.evaluate(async () => {
        const csrf = document.cookie
            .split("; ")
            .find((part) => part.startsWith("tonewatch_csrf="))
            ?.slice("tonewatch_csrf=".length);
        const response = await fetch("/api/tonesets/fixture-page/test", {
            method: "POST",
            headers: csrf ? { "X-CSRF-Token": csrf } : undefined,
        });
        if (!response.ok) throw new Error(`test trigger failed: ${response.status}`);
    });
    await expect(page.getByTestId("map-marker-fixture-agency")).toHaveClass(/marker-pulse/, {
        timeout: 5000,
    });
    await trigger;
    await expect
        .poll(
            async () => {
                const response = await page.request.get(
                    "/api/calls?agency_id=fixture-agency&limit=5",
                );
                const body = (await response.json()) as { items?: unknown[] };
                return body.items?.length ?? 0;
            },
            { timeout: 20000 },
        )
        .toBeGreaterThan(0);
    await page.goto("/calls?agency_id=fixture-agency");
    const call = page.locator('main a[href^="/calls/"]').first();
    await expect(call).toBeVisible({ timeout: 20000 });
    await call.click();
    await expect(page.getByText("Fixture Agency")).toBeVisible();
    expect(external).toEqual([]);
});
