from __future__ import annotations

import asyncio
import os

import structlog
from playwright.async_api import async_playwright

from skyvern.constants import BROWSER_CLOSE_TIMEOUT
from skyvern.exceptions import MissingBrowserState
from skyvern.forge.sdk.schemas.tasks import ProxyLocation, Task
from skyvern.forge.sdk.workflow.models.workflow import WorkflowRun
from skyvern.webeye.browser_factory import BrowserContextFactory, BrowserState, VideoArtifact

LOG = structlog.get_logger()


class BrowserManager:
    instance = None
    pages: dict[str, BrowserState] = dict()

    def __new__(cls) -> BrowserManager:
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    @staticmethod
    async def _create_browser_state(
        proxy_location: ProxyLocation | None = None,
        url: str | None = None,
        task_id: str | None = None,
        workflow_run_id: str | None = None,
        organization_id: str | None = None,
    ) -> BrowserState:
        pw = await async_playwright().start()
        (
            browser_context,
            browser_artifacts,
            browser_cleanup,
        ) = await BrowserContextFactory.create_browser_context(
            pw,
            proxy_location=proxy_location,
            url=url,
            task_id=task_id,
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
        )
        return BrowserState(
            pw=pw,
            browser_context=browser_context,
            page=None,
            browser_artifacts=browser_artifacts,
            browser_cleanup=browser_cleanup,
        )

    async def get_or_create_for_task(self, task: Task) -> BrowserState:
        if task.task_id in self.pages:
            return self.pages[task.task_id]
        elif task.workflow_run_id in self.pages:
            LOG.info(
                "Browser state for task not found. Using browser state for workflow run",
                task_id=task.task_id,
                workflow_run_id=task.workflow_run_id,
            )
            self.pages[task.task_id] = self.pages[task.workflow_run_id]
            return self.pages[task.task_id]

        LOG.info("Creating browser state for task", task_id=task.task_id)
        browser_state = await self._create_browser_state(
            proxy_location=task.proxy_location,
            url=task.url,
            task_id=task.task_id,
            organization_id=task.organization_id,
        )

        # The URL here is only used when creating a new page, and not when using an existing page.
        # This will make sure browser_state.page is not None.
        await browser_state.get_or_create_page(
            url=task.url, proxy_location=task.proxy_location, task_id=task.task_id, organization_id=task.organization_id
        )

        self.pages[task.task_id] = browser_state
        if task.workflow_run_id:
            self.pages[task.workflow_run_id] = browser_state
        return browser_state

    async def get_or_create_for_workflow_run(self, workflow_run: WorkflowRun, url: str | None = None) -> BrowserState:
        if workflow_run.workflow_run_id in self.pages:
            return self.pages[workflow_run.workflow_run_id]
        LOG.info(
            "Creating browser state for workflow run",
            workflow_run_id=workflow_run.workflow_run_id,
        )
        browser_state = await self._create_browser_state(
            workflow_run.proxy_location,
            url=url,
            workflow_run_id=workflow_run.workflow_run_id,
            organization_id=workflow_run.organization_id,
        )

        # The URL here is only used when creating a new page, and not when using an existing page.
        # This will make sure browser_state.page is not None.
        await browser_state.get_or_create_page(
            url=url,
            proxy_location=workflow_run.proxy_location,
            workflow_run_id=workflow_run.workflow_run_id,
            organization_id=workflow_run.organization_id,
        )

        self.pages[workflow_run.workflow_run_id] = browser_state
        return browser_state

    async def get_for_workflow_run(self, workflow_run_id: str) -> BrowserState | None:
        if workflow_run_id in self.pages:
            return self.pages[workflow_run_id]
        return None

    def set_video_artifact_for_task(self, task: Task, artifacts: list[VideoArtifact]) -> None:
        if task.workflow_run_id and task.workflow_run_id in self.pages:
            self.pages[task.workflow_run_id].browser_artifacts.video_artifacts = artifacts
            return
        if task.task_id in self.pages:
            self.pages[task.task_id].browser_artifacts.video_artifacts = artifacts
            return

        raise MissingBrowserState(task_id=task.task_id)

    async def get_video_artifacts(
        self,
        browser_state: BrowserState,
        task_id: str = "",
        workflow_id: str = "",
        workflow_run_id: str = "",
    ) -> list[VideoArtifact]:
        if len(browser_state.browser_artifacts.video_artifacts) == 0:
            LOG.warning(
                "Video data not found for task",
                task_id=task_id,
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
            )
            return []

        for i, video_artifact in enumerate(browser_state.browser_artifacts.video_artifacts):
            path = video_artifact.video_path
            if path and os.path.exists(path=path):
                with open(path, "rb") as f:
                    browser_state.browser_artifacts.video_artifacts[i].video_data = f.read()

        return browser_state.browser_artifacts.video_artifacts

    async def get_har_data(
        self,
        browser_state: BrowserState,
        task_id: str = "",
        workflow_id: str = "",
        workflow_run_id: str = "",
    ) -> bytes:
        if browser_state:
            path = browser_state.browser_artifacts.har_path
            if path and os.path.exists(path=path):
                with open(path, "rb") as f:
                    return f.read()
        LOG.warning(
            "HAR data not found for task",
            task_id=task_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        return b""

    @classmethod
    async def close(cls) -> None:
        LOG.info("Closing BrowserManager")
        for browser_state in cls.pages.values():
            await browser_state.close()
        cls.pages = dict()
        LOG.info("BrowserManger is closed")

    async def cleanup_for_task(self, task_id: str, close_browser_on_completion: bool = True) -> BrowserState | None:
        LOG.info("Cleaning up for task")
        browser_state_to_close = self.pages.pop(task_id, None)
        try:
            if browser_state_to_close:
                async with asyncio.timeout(BROWSER_CLOSE_TIMEOUT):
                    # Stop tracing before closing the browser if tracing is enabled
                    if browser_state_to_close.browser_context and browser_state_to_close.browser_artifacts.traces_dir:
                        trace_path = f"{browser_state_to_close.browser_artifacts.traces_dir}/{task_id}.zip"
                        await browser_state_to_close.browser_context.tracing.stop(path=trace_path)
                        LOG.info("Stopped tracing", trace_path=trace_path)
                    await browser_state_to_close.close(close_browser_on_completion=close_browser_on_completion)
            LOG.info("Task is cleaned up")
        except TimeoutError:
            LOG.warning("Timeout on task cleanup")

        return browser_state_to_close

    async def cleanup_for_workflow_run(
        self,
        workflow_run_id: str,
        task_ids: list[str],
        close_browser_on_completion: bool = True,
    ) -> BrowserState | None:
        LOG.info("Cleaning up for workflow run")
        browser_state_to_close = self.pages.pop(workflow_run_id, None)
        if browser_state_to_close:
            # Stop tracing before closing the browser if tracing is enabled
            if browser_state_to_close.browser_context and browser_state_to_close.browser_artifacts.traces_dir:
                trace_path = f"{browser_state_to_close.browser_artifacts.traces_dir}/{workflow_run_id}.zip"
                await browser_state_to_close.browser_context.tracing.stop(path=trace_path)
                LOG.info("Stopped tracing", trace_path=trace_path)

            await browser_state_to_close.close(close_browser_on_completion=close_browser_on_completion)
        for task_id in task_ids:
            self.pages.pop(task_id, None)
        LOG.info("Workflow run is cleaned up")

        return browser_state_to_close
