import flet as ft

def main(page: ft.Page):
    page.title = "PDF-OPS"
    page.add(
        ft.Text("PDF-OPS", size=30),
    )


ft.app(target=main)