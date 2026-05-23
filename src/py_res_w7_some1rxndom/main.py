import asyncio
import random
import sys
from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from itertools import islice
from pathlib import Path

from httpx import AsyncClient
from pydantic import BaseModel, TypeAdapter, ValidationError
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qasync import QEventLoop, asyncSlot

QSS: str = """
QWidget#StoryWidget QLabel#title {
    font-size: 20px;
    font-weight: bold;
}

QWidget#StoryWidget QLabel#normal {
    font-size: 16px;
}

QWidget#StoryWidget QLabel#normal:link {
    color: #33a7ff;
}

QWidget#StoryWidget QLabel#normal:linkvisited {
    color: #9810fa;
}

QWidget * {
    background-color: #333;
    color: white;
}

QWidget#App {
    background-color: #333;
}

QMessageBox {
    background-color: #333;
    color: white;
}
"""
DATA_PATH = Path(f"data_{__package__ or 'hn_gui'}.json")


class Story(BaseModel, frozen=True):
    title: str
    by: str
    score: int
    descendants: int | None = None
    url: str | None = None


class StoryType(StrEnum):
    New = "https://hacker-news.firebaseio.com/v0/topstories.json"
    Top = "https://hacker-news.firebaseio.com/v0/newstories.json"
    Best = "https://hacker-news.firebaseio.com/v0/beststories.json"

    Ask = "https://hacker-news.firebaseio.com/v0/askstories.json"
    Show = "https://hacker-news.firebaseio.com/v0/showstories.json"
    Job = "https://hacker-news.firebaseio.com/v0/jobstories.json"


class StoryWidget(QWidget):
    def __init__(
        self,
        /,
        parent: QWidget | None = None,
        *,
        story: Story,
    ) -> None:
        super().__init__(parent=parent)
        self.setObjectName("StoryWidget")
        container = QVBoxLayout(self)
        title = QLabel(story.title, self)
        title.setObjectName("title")

        author = QLabel(f"By: {story.by}", self)
        author.setObjectName("normal")
        score = QLabel(f"Score: {story.score}", self)
        score.setObjectName("normal")

        anchor = (
            "<style>a:link{color:#33a7ff;}</style>"
            f'<a href="{story.url}">{story.url}</a>'
            if story.url
            else "(No URL)"
        )
        url = QLabel(anchor, self)
        url.setOpenExternalLinks(True)
        url.setObjectName("normal")

        container.addWidget(title)
        container.addWidget(author)
        container.addWidget(score)

        if story.descendants:
            comments = QLabel(f"{story.descendants} comments")
            comments.setObjectName("normal")
            container.addWidget(comments)

        container.addWidget(url)


class App(QWidget):
    ta = TypeAdapter(list[Story])

    def __init__(self) -> None:
        super().__init__()

        self.httpclient = AsyncClient()
        self.in_progress = False
        self.stories: list[Story] = []
        self.story_widgets: dict[Story, StoryWidget] = {}
        self.story_type = StoryType.New

        ref = QWidget()
        self.story_layout = QVBoxLayout(ref)
        self.story_container = QScrollArea()
        self.story_container.setWidget(ref)
        self.story_container.setWidgetResizable(True)

        self.setWindowTitle("Hacker News Reader")
        self.setObjectName("App")
        self.setStyleSheet(QSS)
        self.setAutoFillBackground(True)
        self.resize(400, 400)

        story_choice = QComboBox(self)
        for each in StoryType:
            story_choice.addItem(each.name, userData=each)

        def update_story_type(_: int, self: App = self) -> None:
            self.story_type = story_choice.currentData()

        story_choice.currentIndexChanged.connect(update_story_type)

        fetch_button = QPushButton("Fetch Articles", self)

        def __button_callback() -> None:
            tasks = set()
            if self.in_progress:
                QMessageBox(
                    QMessageBox.Icon.Information,
                    "INFO",
                    "Articles are alrady being fetched!",
                    parent=self,
                ).exec()
                return
            task = asyncio.ensure_future(self.fetch_stories())
            tasks.add(task)
            task.add_done_callback(tasks.remove)

        fetch_button.clicked.connect(__button_callback)

        self.load_data()

        grid = QVBoxLayout(self)
        grid.addWidget(self.story_container)
        grid.addWidget(story_choice)
        grid.addWidget(fetch_button)

    def load_data(self) -> None:
        if not DATA_PATH.exists():
            return
        try:
            self.render_stories(self.ta.validate_json(DATA_PATH.read_text()))
        except ValidationError as e:
            DATA_PATH.unlink()
            print(f"WARNING: Invalid data file: {e}.\nDeleting...")
            msg_box = QMessageBox(
                QMessageBox.Icon.Warning,
                "WARNING",
                f"Invalid data file.\nDeleting {DATA_PATH.absolute()}...",
                parent=self,
            )
            msg_box.exec()

    def render_stories(self, new: Iterable[Story]) -> None:
        c_old = Counter(self.stories)
        c_new = Counter(new)

        to_add = list(c_new - c_old)
        to_remove = list(c_old - c_new)

        for story in to_add:
            widget = StoryWidget(story=story)
            self.story_widgets[story] = widget
            self.story_layout.addWidget(widget)
        for story in to_remove:
            widget = self.story_widgets[story]
            self.story_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()

        self.stories = list(c_new)

    @asyncSlot(None)
    async def fetch_stories(self) -> None:
        if not random.randint(0, 10):  # noqa: S311
            meows = ["meow", "mrrp", "mrow", "meowowowow"]
            QInputDialog.getItem(self, "meow?", "", meows)

        self.in_progress = True

        stories = [
            Story(**raw)
            async for raw in (
                (
                    await self.httpclient.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{id}.json",
                    )
                ).json()
                for id in islice(
                    (await self.httpclient.get(self.story_type)).json(),
                    10,
                )
            )
        ]
        self.render_stories(stories)
        self.in_progress = False

    def on_close(self) -> None:
        with DATA_PATH.open("wb") as w:
            w.write(self.ta.dump_json(self.stories))


async def _main(root: QApplication) -> None:
    close_event = asyncio.Event()
    root.aboutToQuit.connect(close_event.set)
    app = App()
    root.aboutToQuit.connect(app.on_close)
    app.show()
    await close_event.wait()


def main() -> None:
    root = QApplication(sys.argv)
    asyncio.run(_main(root), loop_factory=QEventLoop)


if __name__ == "__main__":
    main()
