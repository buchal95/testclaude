"""
CLI interface for the Networking Tool.
Based on principles from "Never Eat Alone" by Keith Ferrazzi.
"""

import click
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

from . import database as db

console = Console()

CIRCLE_LABELS = {
    "inner_circle": "Vnitrni kruh",
    "close": "Blizci",
    "acquaintance": "Znami",
    "dormant": "Spici kontakty",
}

CIRCLE_COLORS = {
    "inner_circle": "bold magenta",
    "close": "bold cyan",
    "acquaintance": "bold green",
    "dormant": "dim",
}

INTERACTION_TYPES = ["meal", "coffee", "call", "email", "event", "intro", "other"]

GENEROSITY_CATEGORIES = ["intro", "advice", "resource", "help", "gift", "referral"]


@click.group()
def cli():
    """Networking Tool - Nikdy Nejez Sam

    Nastroj pro budovani a udrzovani vztahu podle knihy
    "Never Eat Alone" od Keitha Ferrazziho.
    """
    db.init_db()


# ============================================================
# DASHBOARD
# ============================================================

@cli.command("dashboard")
def dashboard():
    """Zobraz prehled tvoji networkingove aktivity."""
    stats = db.get_stats()

    # Header
    console.print()
    console.print(Panel(
        "[bold]Networking Dashboard[/bold]\n"
        "Nikdy Nejez Sam",
        style="bold blue",
        expand=False
    ))

    # Circle stats
    circle_table = Table(title="Kontakty podle kruhu", box=box.ROUNDED)
    circle_table.add_column("Kruh", style="bold")
    circle_table.add_column("Pocet", justify="right")
    for circle_key, label in CIRCLE_LABELS.items():
        count = stats["circles"].get(circle_key, 0)
        color = CIRCLE_COLORS.get(circle_key, "")
        circle_table.add_row(f"[{color}]{label}[/{color}]", str(count))
    circle_table.add_row("[bold]Celkem[/bold]", f"[bold]{stats['total_contacts']}[/bold]")

    # Activity stats
    activity_table = Table(title="Aktivita", box=box.ROUNDED)
    activity_table.add_column("Metrika", style="bold")
    activity_table.add_column("Hodnota", justify="right")
    activity_table.add_row("Interakce tento tyden", str(stats["interactions_this_week"]))
    activity_table.add_row("Interakce tento mesic", str(stats["interactions_this_month"]))
    activity_table.add_row("Stedral jsi (tento mesic)", str(stats["generosity_this_month"]))

    followup_color = "red" if stats["overdue_followups"] > 0 else "green"
    activity_table.add_row(
        "Cekajici follow-upy",
        f"[{followup_color}]{stats['pending_followups']}[/{followup_color}]"
    )
    if stats["overdue_followups"] > 0:
        activity_table.add_row(
            "Zpozedene follow-upy",
            f"[bold red]{stats['overdue_followups']}[/bold red]"
        )
    activity_table.add_row("Otevrene cile", str(stats["pending_goals"]))

    console.print(Columns([circle_table, activity_table], padding=(0, 4)))

    # Dormant contacts warning
    if stats["dormant_contacts"]:
        console.print()
        dormant_table = Table(
            title="Spici kontakty (90+ dni bez interakce)",
            box=box.ROUNDED,
            style="yellow"
        )
        dormant_table.add_column("Jmeno", style="bold")
        dormant_table.add_column("Kruh")
        dormant_table.add_column("Posledni interakce")
        for c in stats["dormant_contacts"]:
            label = CIRCLE_LABELS.get(c["circle"], c["circle"])
            last = c["last_interaction"] or "zadna"
            dormant_table.add_row(c["name"], label, last)
        console.print(dormant_table)
        console.print(
            "[yellow]Tip: Obnov kontakt s temito lidmi - staci kratky email nebo kava![/yellow]"
        )

    console.print()


# ============================================================
# CONTACTS
# ============================================================

@cli.group("contact")
def contact_group():
    """Sprava kontaktu."""
    pass


@contact_group.command("add")
@click.argument("name")
@click.option("--email", "-e", help="E-mail")
@click.option("--phone", "-p", help="Telefon")
@click.option("--company", "-c", help="Firma")
@click.option("--role", "-r", help="Pozice")
@click.option("--circle", type=click.Choice(list(CIRCLE_LABELS.keys())),
              default="acquaintance", help="Kruh vztahu")
@click.option("--notes", "-n", help="Poznamky")
@click.option("--met", help="Jak jste se potkali")
@click.option("--interests", help="Zajmy (oddelene carkou)")
@click.option("--goals", help="Co pro nej/ni chces udelat")
def contact_add(name, email, phone, company, role, circle, notes, met, interests, goals):
    """Pridej novy kontakt."""
    contact_id = db.add_contact(
        name=name, email=email, phone=phone, company=company,
        role=role, circle=circle, notes=notes, how_we_met=met,
        interests=interests, goals=goals
    )
    label = CIRCLE_LABELS[circle]
    console.print(f"[green]Kontakt '{name}' pridan (ID: {contact_id}, kruh: {label})[/green]")


@contact_group.command("list")
@click.option("--circle", type=click.Choice(list(CIRCLE_LABELS.keys())),
              help="Filtruj podle kruhu")
def contact_list(circle):
    """Vypis vsechny kontakty."""
    contacts = db.list_contacts(circle)
    if not contacts:
        console.print("[yellow]Zadne kontakty nenalezeny.[/yellow]")
        return

    table = Table(title="Kontakty", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Jmeno", style="bold")
    table.add_column("Firma")
    table.add_column("Pozice")
    table.add_column("Kruh")
    table.add_column("E-mail")

    for c in contacts:
        label = CIRCLE_LABELS.get(c["circle"], c["circle"])
        color = CIRCLE_COLORS.get(c["circle"], "")
        table.add_row(
            str(c["id"]),
            c["name"],
            c["company"] or "",
            c["role"] or "",
            f"[{color}]{label}[/{color}]",
            c["email"] or "",
        )
    console.print(table)


@contact_group.command("show")
@click.argument("contact_id", type=int)
def contact_show(contact_id):
    """Zobraz detail kontaktu."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return

    label = CIRCLE_LABELS.get(c["circle"], c["circle"])
    color = CIRCLE_COLORS.get(c["circle"], "")

    info = f"""[bold]{c['name']}[/bold]
[{color}]{label}[/{color}]

Firma:      {c['company'] or '-'}
Pozice:     {c['role'] or '-'}
E-mail:     {c['email'] or '-'}
Telefon:    {c['phone'] or '-'}
Zajmy:      {c['interests'] or '-'}
Jak jsme se potkali: {c['how_we_met'] or '-'}
Cile:       {c['goals'] or '-'}
Poznamky:   {c['notes'] or '-'}
Pridan:     {c['created_at']}"""

    console.print(Panel(info, title=f"Kontakt #{c['id']}", box=box.ROUNDED))

    # Recent interactions
    interactions = db.get_interactions(contact_id, limit=5)
    if interactions:
        table = Table(title="Posledni interakce", box=box.SIMPLE)
        table.add_column("Datum")
        table.add_column("Typ")
        table.add_column("Popis")
        table.add_column("Follow-up")
        for i in interactions:
            fu_status = ""
            if i["follow_up_needed"]:
                fu_status = "[green]Hotovo[/green]" if i["follow_up_done"] else "[red]Ceka[/red]"
            table.add_row(i["date"], i["type"], i["description"] or "", fu_status)
        console.print(table)

    # Generosity
    generosity = db.get_generosity(contact_id)
    if generosity:
        table = Table(title="Stedrost (co jsi dal/udelal)", box=box.SIMPLE)
        table.add_column("Datum")
        table.add_column("Kategorie")
        table.add_column("Popis")
        for g in generosity:
            table.add_row(g["date"], g["category"] or "", g["description"])
        console.print(table)

    # Goals
    goals = db.get_goals(contact_id)
    if goals:
        table = Table(title="Cile vztahu", box=box.SIMPLE)
        table.add_column("Cil")
        table.add_column("Do kdy")
        table.add_column("Stav")
        for g in goals:
            status = "[green]Splneno[/green]" if g["completed"] else "[yellow]Otevreny[/yellow]"
            table.add_row(g["goal"], g["target_date"] or "-", status)
        console.print(table)


@contact_group.command("search")
@click.argument("query")
def contact_search(query):
    """Hledej kontakty podle jmena, firmy nebo poznamek."""
    contacts = db.search_contacts(query)
    if not contacts:
        console.print(f"[yellow]Zadne vysledky pro '{query}'.[/yellow]")
        return

    table = Table(title=f"Vysledky hledani: '{query}'", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Jmeno", style="bold")
    table.add_column("Firma")
    table.add_column("Kruh")

    for c in contacts:
        label = CIRCLE_LABELS.get(c["circle"], c["circle"])
        color = CIRCLE_COLORS.get(c["circle"], "")
        table.add_row(str(c["id"]), c["name"], c["company"] or "",
                      f"[{color}]{label}[/{color}]")
    console.print(table)


@contact_group.command("edit")
@click.argument("contact_id", type=int)
@click.option("--name", help="Jmeno")
@click.option("--email", help="E-mail")
@click.option("--phone", help="Telefon")
@click.option("--company", help="Firma")
@click.option("--role", help="Pozice")
@click.option("--circle", type=click.Choice(list(CIRCLE_LABELS.keys())), help="Kruh")
@click.option("--notes", help="Poznamky")
@click.option("--met", "how_we_met", help="Jak jste se potkali")
@click.option("--interests", help="Zajmy")
@click.option("--goals", help="Cile")
def contact_edit(contact_id, **fields):
    """Uprav kontakt."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return
    db.update_contact(contact_id, **fields)
    console.print(f"[green]Kontakt #{contact_id} aktualizovan.[/green]")


@contact_group.command("delete")
@click.argument("contact_id", type=int)
@click.confirmation_option(prompt="Opravdu chces smazat tento kontakt?")
def contact_delete(contact_id):
    """Smaz kontakt."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return
    db.delete_contact(contact_id)
    console.print(f"[green]Kontakt '{c['name']}' smazan.[/green]")


# ============================================================
# INTERACTIONS
# ============================================================

@cli.group("interaction")
def interaction_group():
    """Zaznamenavani interakci s kontakty."""
    pass


@interaction_group.command("add")
@click.argument("contact_id", type=int)
@click.option("--type", "interaction_type", type=click.Choice(INTERACTION_TYPES),
              required=True, help="Typ interakce")
@click.option("--desc", "-d", help="Popis")
@click.option("--date", help="Datum (YYYY-MM-DD, default: dnes)")
@click.option("--followup/--no-followup", default=False, help="Potrebuje follow-up?")
@click.option("--followup-by", help="Follow-up do (YYYY-MM-DD)")
def interaction_add(contact_id, interaction_type, desc, date, followup, followup_by):
    """Zaznamenej interakci s kontaktem."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return

    if followup and not followup_by:
        # Pravidlo 24 hodin z knihy
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        followup_by = tomorrow
        console.print(f"[cyan]Pravidlo 24 hodin: Follow-up nastaven do {tomorrow}[/cyan]")

    interaction_id = db.add_interaction(
        contact_id, interaction_type, desc, date, followup, followup_by
    )
    console.print(
        f"[green]Interakce #{interaction_id} zaznamenana "
        f"({interaction_type} s {c['name']})[/green]"
    )


@interaction_group.command("list")
@click.argument("contact_id", type=int)
@click.option("--limit", "-l", default=20, help="Pocet zaznamu")
def interaction_list(contact_id, limit):
    """Zobraz interakce s kontaktem."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return

    interactions = db.get_interactions(contact_id, limit)
    if not interactions:
        console.print(f"[yellow]Zadne interakce s {c['name']}.[/yellow]")
        return

    table = Table(title=f"Interakce s {c['name']}", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Datum")
    table.add_column("Typ", style="bold")
    table.add_column("Popis")
    table.add_column("Follow-up")

    for i in interactions:
        fu_status = ""
        if i["follow_up_needed"]:
            if i["follow_up_done"]:
                fu_status = "[green]Hotovo[/green]"
            else:
                overdue = i["follow_up_by"] and i["follow_up_by"] < datetime.now().strftime("%Y-%m-%d")
                if overdue:
                    fu_status = f"[bold red]ZPOZDEN ({i['follow_up_by']})[/bold red]"
                else:
                    fu_status = f"[yellow]Do {i['follow_up_by'] or '?'}[/yellow]"
        table.add_row(
            str(i["id"]), i["date"], i["type"],
            i["description"] or "", fu_status
        )
    console.print(table)


# ============================================================
# FOLLOW-UPS
# ============================================================

@cli.command("followups")
def followups():
    """Zobraz vsechny cekajici follow-upy (pravidlo 24 hodin!)."""
    pending = db.get_pending_followups()
    if not pending:
        console.print("[green]Zadne cekajici follow-upy. Skvela prace![/green]")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    table = Table(title="Cekajici Follow-upy", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Kontakt", style="bold")
    table.add_column("Kruh")
    table.add_column("Typ interakce")
    table.add_column("Datum interakce")
    table.add_column("Follow-up do")
    table.add_column("Stav")

    for f in pending:
        label = CIRCLE_LABELS.get(f["circle"], f["circle"])
        overdue = f["follow_up_by"] and f["follow_up_by"] < today
        status = "[bold red]ZPOZDEN[/bold red]" if overdue else "[yellow]Ceka[/yellow]"
        deadline = f["follow_up_by"] or "-"
        if overdue:
            deadline = f"[bold red]{deadline}[/bold red]"
        table.add_row(
            str(f["id"]), f["contact_name"], label,
            f["type"], f["date"], deadline, status
        )
    console.print(table)
    console.print(
        "\n[cyan]Tip z knihy: 'Follow-up je klicovy. "
        "Posli email do 24 hodin po setkani!'[/cyan]"
    )


@cli.command("done")
@click.argument("interaction_id", type=int)
def mark_done(interaction_id):
    """Oznac follow-up jako splneny."""
    db.mark_followup_done(interaction_id)
    console.print(f"[green]Follow-up #{interaction_id} oznacen jako splneny.[/green]")


# ============================================================
# GENEROSITY
# ============================================================

@cli.group("give")
def give_group():
    """Sledovani stedrosti - davej driv nez prosim (klicovy princip!)."""
    pass


@give_group.command("add")
@click.argument("contact_id", type=int)
@click.option("--desc", "-d", required=True, help="Co jsi udelal/dal")
@click.option("--category", "-c", type=click.Choice(GENEROSITY_CATEGORIES),
              help="Kategorie")
@click.option("--date", help="Datum (YYYY-MM-DD)")
def give_add(contact_id, desc, category, date):
    """Zaznamenej akt stedrosti."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return
    gen_id = db.add_generosity(contact_id, desc, category, date)
    console.print(
        f"[green]Stedrost #{gen_id} zaznamenana pro {c['name']}[/green]\n"
        f"[cyan]'Vztahy se budujou tim, ze davas, ne ze beres.' - Ferrazzi[/cyan]"
    )


@give_group.command("list")
@click.argument("contact_id", type=int)
def give_list(contact_id):
    """Zobraz historii stedrosti pro kontakt."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return

    items = db.get_generosity(contact_id)
    if not items:
        console.print(f"[yellow]Zadne zaznamy stedrosti pro {c['name']}.[/yellow]")
        return

    table = Table(title=f"Stedrost pro {c['name']}", box=box.ROUNDED)
    table.add_column("Datum")
    table.add_column("Kategorie")
    table.add_column("Popis")
    for g in items:
        table.add_row(g["date"], g["category"] or "-", g["description"])
    console.print(table)


# ============================================================
# GOALS
# ============================================================

@cli.group("goal")
def goal_group():
    """Akcni plany vztahu - definuj cile pro kazdy kontakt."""
    pass


@goal_group.command("add")
@click.argument("contact_id", type=int)
@click.option("--goal", "-g", required=True, help="Popis cile")
@click.option("--by", "target_date", help="Cilovy datum (YYYY-MM-DD)")
def goal_add(contact_id, goal, target_date):
    """Pridej cil vztahu."""
    c = db.get_contact(contact_id)
    if not c:
        console.print(f"[red]Kontakt s ID {contact_id} nenalezen.[/red]")
        return
    goal_id = db.add_goal(contact_id, goal, target_date)
    console.print(f"[green]Cil #{goal_id} pridan pro {c['name']}[/green]")


@goal_group.command("list")
@click.option("--contact", "-c", "contact_id", type=int, help="Filtruj podle kontaktu")
@click.option("--pending/--all", default=True, help="Jen nesplnene")
def goal_list(contact_id, pending):
    """Zobraz cile vztahu."""
    goals = db.get_goals(contact_id, pending_only=pending)
    if not goals:
        console.print("[yellow]Zadne cile nenalezeny.[/yellow]")
        return

    table = Table(title="Cile vztahu", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Kontakt", style="bold")
    table.add_column("Cil")
    table.add_column("Do kdy")
    table.add_column("Stav")

    for g in goals:
        status = "[green]Splneno[/green]" if g["completed"] else "[yellow]Otevreny[/yellow]"
        table.add_row(
            str(g["id"]), g["contact_name"], g["goal"],
            g["target_date"] or "-", status
        )
    console.print(table)


@goal_group.command("done")
@click.argument("goal_id", type=int)
def goal_done(goal_id):
    """Oznac cil jako splneny."""
    db.complete_goal(goal_id)
    console.print(f"[green]Cil #{goal_id} splnen![/green]")


# ============================================================
# TIPS - Tipy z knihy
# ============================================================

@cli.command("tips")
def tips():
    """Zobraz klicove principy z knihy 'Nikdy Nejez Sam'."""
    tips_list = [
        ("Nikdy nejez sam",
         "Kazde jidlo je prilezitost k budovani vztahu. "
         "Nepromarnuj obed u stolu sam."),
        ("Buduj vztahy PRED tim, nez je potrebujes",
         "Networking neni o tom prosit o laskavosti. "
         "Zacni budovat vztahy ted, ne az budes neco potrebovat."),
        ("Pravidlo 24 hodin",
         "Po kazdem setkani posli follow-up do 24 hodin. "
         "Kratky email, SMS, nebo LinkedIn zprava."),
        ("Bud stedry - davej driv nez prosim",
         "Nejlepsi networkers davaji vic nez berou. "
         "Predstavuj lidi, sdilej zdroje, nabizej pomoc."),
        ("Sdilej sve vase a zajmy",
         "Lide se pripojuji k lidem, ne k zivotopism. "
         "Bud autenticky a sdilej co te bavi."),
        ("Vytvor si 'Relationship Action Plan'",
         "Pro kazdy dulezity kontakt si stanovte konkretni cile "
         "a kroky, jak vztah prohloubit."),
        ("Stanej se konektorem",
         "Propojuj lide ve svem okolí. Bud mostem mezi svetem. "
         "Kazde propojeni posiluje tvou sit."),
        ("Buduj svuj vnitrni kruh",
         "Identifikuj 5-10 klicovych lidi, se kterymi investujes nejvice. "
         "Tito lide jsou tvuj zaklad."),
        ("Bud zajimany, ne zajmavy",
         "Ptej se, naslouchej, zajimej se uprimne o druhe. "
         "Nejlepsi networkeri jsou nejlepsi posluchaci."),
        ("Neveď si skore",
         "Nesleduj kdo komu co dluzi. "
         "Stedrost bez ocekavani se vzdy vrati."),
    ]

    console.print()
    for i, (title, desc) in enumerate(tips_list, 1):
        console.print(Panel(
            f"[bold]{title}[/bold]\n\n{desc}",
            title=f"Tip #{i}",
            box=box.ROUNDED,
            style="cyan",
            expand=False
        ))
    console.print()
