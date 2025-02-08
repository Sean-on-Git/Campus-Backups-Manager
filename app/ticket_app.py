from rich.text import Text
from textual.app import App
from textual.widgets import Header, Footer, DataTable, Static, Input, Button, ProgressBar
from textual.containers import Container
from textual.reactive import reactive
from textual.events import Key
import webbrowser
import asyncio
from api_utils import move_to_deletion_folder, scan_directory_for_tickets, fetch_ticket_info, BACKUPS_LOCATION, INSTANCE

class TicketApp(App):
    CSS_PATH = "style.tcss"
    selected_index: reactive[int] = reactive(0)
    ticket_info_list: reactive[list] = reactive([])

    def compose(self):
        """
        Compose the app layout with all the necessary widgets and containers.

        Yields:
            Container: The main layout containers and widgets.
        """
        self.bottom_row = Static("Ctrl+Q to quit | Enter to open ticket in browser | Tab and arrow keys to navigate", classes="bold")
        yield Header()
        yield self.login_container()
        yield DataTable(id="data_table")
        yield ProgressBar(id="progress_bar")

        self.deletion_table = DataTable(id="deletion_table")
        self.deletion_table.add_columns("Ticket Number", "Closed At (Local)", "Closed By Username", "Ready for Pickup Tag", "Ready for Deletion")
        self.deletion_table.cursor_type = "row"
        self.deletion_table.focus()
        self.deletion_confirmation_text = Static("Are you sure ALL of these folders are ready to be moved to the 'MARKED FOR DELETION' folder?")
        self.deletion_container = Container(
            self.deletion_table,
            self.deletion_confirmation_text,
            Button("No", id="no_button", variant="error"),
            Button("Yes", id="yes_button", variant="success")
        )
        self.deletion_container.id = "deletion_container"
        self.deletion_container.styles.display = "none" 
        yield self.deletion_container
        login_error = Static("Incorrect Username or Password. Quit application and try again")
        login_error.id = "login_error"
        yield login_error
        
        self.title = 'HDCS Backup Management Utility'

        yield self.bottom_row
        yield Footer(self.bottom_row)

    def login_container(self):
        """
        Create the login container with input fields for username and password.

        Returns:
            Container: The login container with input fields and login button.
        """
        return Container(
            Static(f"ServiceNow Instance: {INSTANCE}", classes="bold"),
            Static("Username:", classes="bold"),
            Input(id="username", placeholder="Username"),
            Static("Password:", classes="bold"),
            Input(id="password", placeholder="Password", password=True),
            Button("Login", id="login_button")
        )
    
    def show(self, id):
        """
        Method to change display of Textual Widget to 'block'

        Args:
            id (str): String of the ID of a certain widget
        """
        self.query_one(id).styles.display = "block"
    
    def hide(self, id):
        """
        Method to change display of Textual Widget to 'none'

        Args:
            id (str): String of the ID of a certain widget
        """
        self.query_one(id).styles.display = "none"

    def on_mount(self):
        """
        Method called when the app is mounted. Initialize and display the main table and progress bar.
        """
        self.bottom_row.styles.bold = True
        self.table = self.query_one("#data_table")
        self.table.add_columns("Ticket Number", "Size", "Closed At (Local)", "Closed By Username", "Ready for Pickup Tag", "Ready for Deletion")
        self.table.cursor_type = "row"
        self.table.focus()
        self.query_one(Container).styles.display = "block"
        self.query_one("#data_table").styles.display = "none"
        self.query_one(ProgressBar).styles.display = "none"
        self.query_one("#deletion_container").styles.display = "none"
        self.query_one("#login_error").styles.display = "none"

    async def on_button_pressed(self, event):
        """
        Handle button pressed events, including login, deletion confirmation, and cancellation.

        Args:
            event (Button.Pressed): The button pressed event.
        """
        if event.button.id == "login_button":
            self.query_one(Container).styles.display = "none"
            self.query_one(DataTable).styles.display = "none"
            self.query_one(ProgressBar).styles.display = "block"
            self.username = self.query_one("#username").value
            self.password = self.query_one("#password").value
            await self.load_tickets(INSTANCE, self.username, self.password)
        elif event.button.id == "no_button":
            self.show("#data_table")
            self.hide("#deletion_container")
        elif event.button.id == "yes_button":
            deletion_info_list = [info for info in self.ticket_info_list if info['ready_for_deletion']]
            ticket_numbers = [info['ticket_number'] for info in deletion_info_list]
            move_to_deletion_folder(ticket_numbers)
            self.show("#data_table")
            self.hide("#deletion_container")

    async def fetch_ticket_info_task(self, instance, username, password, ticket_number):
        """
        Fetch information for a specific ticket asynchronously and update the progress.

        Args:
            instance (str): ServiceNow instance.
            username (str): Username for authentication.
            password (str): Password for authentication.
            ticket_number (str): Ticket number.
        """
        try:
            ticket_info = await asyncio.to_thread(fetch_ticket_info, instance, username, password, ticket_number)
            if ticket_info:
                self.ticket_info_list.append(ticket_info)
                self.call_later(self.update_progress)
        except Exception as e:
            self.show("#login_error")
            self.hide("#data_table")
            self.query_one("#login_error").styles.color = "red"
            print(f"Error fetching ticket info: {e}")
    
    def update_progress(self):
        """
        Update the progress bar by advancing its value.
        """
        progress = self.query_one(ProgressBar)
        progress.advance(1)

    async def load_tickets(self, instance, username, password):
        """
        Load ticket information for all tickets in the backups location.

        Args:
            instance (str): ServiceNow instance.
            username (str): Username for authentication.
            password (str): Password for authentication.
        """
        ticket_numbers = scan_directory_for_tickets(BACKUPS_LOCATION)
        self.ticket_info_list = []
        total_tickets = len(ticket_numbers)
        progress = self.query_one(ProgressBar)
        progress.styles.display = "block"
        progress.total = total_tickets
        tasks = []
        for ticket_number in ticket_numbers:
            task = asyncio.create_task(self.fetch_ticket_info_task(instance, username, password, ticket_number))
            tasks.append(task)
        await asyncio.gather(*tasks)
        await self.populate_table()
    
    async def populate_table(self):
        """
        Populate the data table with the fetched ticket information.
        """
        self.table.clear()
        for info in self.ticket_info_list:
            row_style = ''
            if info['ready_for_deletion']:
                row_style = "bold"
            self.table.add_row(
                Text(info['ticket_number']),
                Text(str(info['folder_size'])),
                Text(info['closed_at_local'], style=row_style),
                Text(info['closed_by_username'], style=row_style),
                Text(str(info['has_ready_for_pickup_tag']), style=row_style),
                Text(str(info['ready_for_deletion']), style=row_style)
            )
        self.query_one(DataTable).styles.display = "block"
        self.query_one(ProgressBar).styles.display = "none"

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """
        Handle the event when a row is selected in the data table.

        Args:
            event (DataTable.RowSelected): The data table row selected event.
        """
        selected_index = event.cursor_row
        selected_row = self.ticket_info_list[selected_index]
        ticket_number = selected_row['ticket_number']
        url = selected_row['url']
        webbrowser.open(url)
        print(f"Selected Ticket: {ticket_number}")

    def on_key(self, event):
        """
        Handle key events, such as showing the deletion confirmation.

        Args:
            event (Key): The key event.
        """
        table = self.query_one(DataTable)
        if isinstance(event, Key):
            if event.key == "x":
                self.query_one("#deletion_container").styles.display = "block"
                self.query_one(DataTable).styles.display = "none"
                self.show_deletion_confirmation()

    def show_deletion_confirmation(self):
        """
        Display the deletion confirmation container with the list of folders ready for deletion.
        """
        deletion_info_list = [info for info in self.ticket_info_list if info['ready_for_deletion']]
        
        if not deletion_info_list:
            # Handle the case where there are no tickets ready for deletion
            self.deletion_table.clear()
            self.deletion_confirmation_text.update("No tickets are ready for deletion.")
        else:
            self.deletion_table.clear()
            for info in deletion_info_list:
                row_style = ''
                if info['ready_for_deletion']:
                    row_style = "bold"
                self.deletion_table.add_row(
                    Text(info['ticket_number'], style=row_style),
                    Text(info['closed_at_local'], style=row_style),
                    Text(info['closed_by_username'], style=row_style),
                    Text(str(info['has_ready_for_pickup_tag']), style=row_style),
                    Text(str(info['ready_for_deletion']), style=row_style)
                )
            self.deletion_confirmation_text.update("Are you sure ALL of these folders are ready to be moved to the 'MARKED FOR DELETION' folder?")
        self.query_one("#data_table").styles.display = "none"
        self.deletion_container.styles.display = "block"



if __name__ == "__main__":
    app = TicketApp()
    app.run()
