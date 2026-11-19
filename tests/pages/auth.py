from playwright.sync_api import Page, Response


class AuthPage:
    def __init__(self, page: Page):
        self.page = page

    def register(self, endpoint: str, username: str, email: str, password: str) -> Response:
        self.page.goto("/register")
        self.page.get_by_label("Username", exact=True).fill(username)
        self.page.get_by_label("Email", exact=True).fill(email)
        self.page.get_by_label("Password", exact=True).fill(password)
        submit = self.page.get_by_role("button", name="Sign up", exact=True)
        with self.page.expect_response(lambda response: response.url == endpoint) as submission:
            submit.click()
        return submission.value

    def sign_in(self, endpoint: str, email: str, password: str) -> Response:
        self.page.goto("/login")
        self.page.get_by_label("Email", exact=True).fill(email)
        self.page.get_by_label("Password", exact=True).fill(password)
        submit = self.page.get_by_role("button", name="Sign in", exact=True)
        with self.page.expect_response(lambda response: response.url == endpoint) as submission:
            submit.click()
        return submission.value

    def sign_in_heading_is_visible(self) -> bool:
        return self.page.get_by_role("heading", name="Sign in", exact=True).is_visible()
