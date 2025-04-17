from rich.text import Text
from textual.app import App
from textual.widgets import ListView, ListItem, Checkbox, Label, Header, Footer, DataTable, Static, Input, Button, ProgressBar
from textual.containers import Container, Center, VerticalScroll
from textual.reactive import reactive
from textual.events import Key
import webbrowser
import asyncio
from api_utils import (
    move_to_deletion_folder, scan_directory_for_tickets, fetch_ticket_info,
    error_logger, debug_logger,
    BACKUPS_LOCATION, INSTANCE, DELETION_LOCATION, APPLICATION_PATH
)

class TicketApp(App):
    CSS_PATH = APPLICATION_PATH + "style.tcss"
    selected_index: reactive[int] = reactive(0)
    ticket_info_list: reactive[list] = reactive([])

    is_deletion_list_created: bool = False

    def compose(self):
        """
        Compose the app layout with all the necessary widgets and containers.

        Yields:
            Container: The main layout containers and widgets.
        """
        yield Header()
        login_container = self.login_container()
        login_container.id = "login_container"
        yield login_container

        self.main_table = self.create_table(
            "data_table", [
                "Ticket Number",
                "Size",
                "Closed At (Local)",
                "Closed By Username",
                "Ready for Pickup Tag",
                "Ready for Deletion"
            ]
        )
        self.main_container = self.create_container(
            "main_container",
            [
                self.main_table,
                Button("Move to Deletion", id="move_deletion"),
                Button("Empty Delete Folder (DO NOT USE YET)", id="perm_delete")
            ]
        )
        yield self.main_container
        
        with Center(id="progress_container"):
            yield Label("Loading Service Now API", id="progress_label")
            yield ProgressBar(id="progress_bar", show_eta=False)

        self.scroll_center = Center()
        self.scroll = VerticalScroll(self.scroll_center, id="delete_center_container")

        # self.deletion_table = self.create_table("deletion_table", ["Checkbox", "Ticket Number", "Closed At (Local)", "Closed By Username", "Ready for Pickup Tag", "Ready for Deletion"])
        # self.deletion_table.cursor_type = "row"
        self.deletion_confirmation_text = Static("Are you sure ALL of these folders are ready to be moved to the 'MARKED FOR DELETION' folder?")
        self.deletion_container = Container(
            self. scroll,
            self.deletion_confirmation_text,
            Button("No", id="no_deletion_button", variant="error"),
            Button("Yes", id="yes_deletion_button", variant="success")
        )
        self.deletion_container.id = "deletion_container"
        self.deletion_container.styles.display = "none" 
        yield self.deletion_container
     
        login_error = Static("Incorrect Username or Password. Quit application and try again")
        login_error.id = "login_error"
        yield login_error
        
        self.title = 'HDCS Backup Management Utility'

        bottom_row = Static("Ctrl+Q to quit | Enter to open ticket in browser | Tab and arrow keys to navigate", classes="bold")
        bottom_row.styles.text_align = "center"

        yield self.create_container("test", [bottom_row])

        # yield bottom_row
        yield Footer()

    def create_table(self, id, columns) -> DataTable:
        """
        Creates data table widget

        Args:
            id (str): ID for new table
            columns ([str]): List of columns for the new table
        """
        table = DataTable(id=id)
        table.add_columns(*columns)
        table.cursor_type = "row"
        return table
    
    def create_container(self, id, widgets) -> Container:
        """
        Create container widget to hold other widgets

        Args:
            id (str): #ID of container
        """
        container = Container(*widgets)
        container.id = id

        return container

    def login_container(self) -> Container:
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
    
    def show(self, id) -> None:
        """
        Method to change display of Textual Widget to 'block'

        Args:
            id (str): String of the ID of a certain widget
        """
        self.query_one(id).styles.display = "block"
    
    def hide(self, id) -> None:
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
        #self.show("#data_table")
        self.query_one("#username").focus()
        self.show("#login_container")
        self.hide("#main_container")
        self.hide("#progress_container")
        self.hide("#deletion_container")
        self.hide("#login_error")

    async def on_button_pressed(self, event):
        """
        Handle button pressed events, including login, deletion confirmation, and cancellation.

        Args:
            event (Button.Pressed): The button pressed event.
        """
        if event.button.id == "login_button":
            self.hide("#login_container")
            self.hide("#main_container")
            self.show("#progress_container")
            self.username = self.query_one("#username").value
            self.password = self.query_one("#password").value
            await self.load_tickets(INSTANCE, self.username, self.password, BACKUPS_LOCATION, self.main_table)
            self.show("#main_container")
            self.query_one("#data_table").focus()
        elif event.button.id == "no_deletion_button":
            self.show("#main_container")
            self.hide("#deletion_container")
            self.query_one("#data_table").focus()
        elif event.button.id == "yes_deletion_button":
            ticket_numbers = [ checkbox.id.split("_")[1] for checkbox in self.query('Checkbox') if checkbox.value ]
            
            debug_logger.debug(f"MOVE TO DELETION: {ticket_numbers}")
            
            #deletion_info_list = [info for info in self.ticket_info_list if info['ready_for_deletion']]
            #ticket_numbers = [info['ticket_number'] for info in deletion_info_list]
            move_to_deletion_folder(ticket_numbers)
            await self.load_tickets(INSTANCE, self.username, self.password, BACKUPS_LOCATION, self.main_table)
            self.show("#main_container")
            self.query_one("#data_table").focus()
            self.hide("#deletion_container")
        elif event.button.id == "move_deletion":
            self.query_one("#deletion_container").styles.display = "block"
            self.query_one("#main_container").styles.display = "none"
            self.show_deletion_confirmation()
        elif event.button.id == "perm_delete":
            await self.load_tickets(INSTANCE, self.username, self.password, DELETION_LOCATION)

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
                #self.call_later(self.update_progress)
                self.update_progress(ticket_number)
        except Exception as e:
            self.show("#login_error")
            self.hide("#main_container")
            self.query_one("#login_error").styles.color = "red"
            error_logger.error(f"Error fetching ticket info: {e}")
            exit()
    
    def update_progress(self, ticket_number):
        """
        Update the progress bar by advancing its value.
        """
        progress = self.query_one("#progress_bar")
        label = self.query_one("#progress_label")
        label.update(f"Loaded {ticket_number}...")
        progress.advance(1)

    async def load_tickets(self, instance, username, password, directory, table):
        """
        Load ticket information for all tickets in the backups location.

        Args:
            instance (str): ServiceNow instance.
            username (str): Username for authentication.
            password (str): Password for authentication.
            directory (str): Directory of backup folders.
            table (DataTable): DataTable widget to populate with data.
        """
        ticket_numbers = scan_directory_for_tickets(directory)
        self.ticket_info_list = []
        total_tickets = len(ticket_numbers)
        self.show("#progress_container")
        progress = self.query_one("#progress_bar")
        progress.total = total_tickets
        tasks = []
        for ticket_number in ticket_numbers:
            task = asyncio.create_task(self.fetch_ticket_info_task(instance, username, password, ticket_number))
            tasks.append(task)
        await asyncio.gather(*tasks)
        await self.populate_table(table)
    
    async def populate_table(self, table):
        """
        Populate the data table with the fetched ticket information.
        """
        table.clear()
        for info in self.ticket_info_list:
            row_style = ''
            if info['ready_for_deletion']:
                row_style = "bold"
            table.add_row(
                Text(info['ticket_number']),
                Text(str(info['folder_size'])),
                Text(info['closed_at_local'], style=row_style),
                Text(info['closed_by_username'], style=row_style),
                Text(str(info['has_ready_for_pickup_tag']), style=row_style),
                Text(str(info['ready_for_deletion']), style=row_style)
            )
        self.query_one(DataTable).styles.display = "block"
        self.hide("#progress_container")

    async def populate_deletion_table(self, table):
        """
        Populate the data table with the fetched ticket information.
        """
        table.clear()
        for info in self.ticket_info_list:
            row_style = ''
            if info['ready_for_deletion']:
                row_style = "bold"
            table.add_row(
                Text(info['ticket_number']),
                Text(str(info['folder_size'])),
                Text(info['closed_at_local'], style=row_style),
                Text(info['closed_by_username'], style=row_style),
                Text(str(info['has_ready_for_pickup_tag']), style=row_style),
                Text(str(info['ready_for_deletion']), style=row_style)
            )
        self.query_one(DataTable).styles.display = "block"
        self.hide("#progress_container")

    def create_delete_checklist(self, deletion_info_list):
        # deletion_info_list = [info for info in self.ticket_info_list if info['ready_for_deletion']]
        
        if not self.is_deletion_list_created:
            for info in deletion_info_list:
                self.scroll_center.mount(
                    Checkbox(
                        f"{info['ticket_number']} - {info['closed_at_local']} - {info['closed_by_username']}",
                        classes="deletion_queue",
                        id=f"checkbox_{info['ticket_number']}"
                    )
                )
            self.is_deletion_list_created = True

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

    def show_deletion_confirmation(self):
        """
        Display the deletion confirmation container with the list of folders ready for deletion.
        """
        deletion_info_list = [info for info in self.ticket_info_list if info['ready_for_deletion']]
        
        if not deletion_info_list:
            # Handle the case where there are no tickets ready for deletion
            # self.deletion_table.clear()
            self.deletion_confirmation_text.update("No tickets are ready for deletion.")
        else:
            # self.deletion_table.clear()
            #for info in deletion_info_list:
            #    row_style = ''
            #    checkbox = Checkbox()
            #    # checkbox.id = info['ticket_number']
            #    if info['ready_for_deletion']:
            #        row_style = "bold"
            #    self.deletion_table.add_row(
            #        checkbox,
            #        Text(info['ticket_number'], style=row_style),
            #        Text(info['closed_at_local'], style=row_style),
            #        Text(info['closed_by_username'], style=row_style),
            #        Text(str(info['has_ready_for_pickup_tag']), style=row_style),
            #        Text(str(info['ready_for_deletion']), style=row_style)
            #    )

            #center = Center(id="delete_center_container")
            #scroll = VerticalScroll()

            #for info in deletion_info_list:
            #    self.scroll.append(Checkbox(f"{info['ticket_number']} - {info['closed_at_local']} - {info['closed_by_username']}"))

            self.create_delete_checklist(deletion_info_list)

            #with center:
            #    yield scroll

            #yield center

            self.deletion_confirmation_text.update("Are you sure ALL of these folders are ready to be moved to the 'MARKED FOR DELETION' folder?")
        self.hide("#main_container")
        self.deletion_container.styles.display = "block"



if __name__ == "__main__":
    app = TicketApp()
    app.run()
