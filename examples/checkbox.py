from telegrinder import Telegrinder, API, Token, Message, Checkbox
from telegrinder.bot.rules import Text
import logging

api = API(token=Token.from_env())
bot = Telegrinder(api)
logging.basicConfig(level=logging.INFO)


@bot.on.message(Text("/checkbox"))
async def action(m: Message):
    picked, m_id = await (
        Checkbox(m.chat.id, "Check your checkbox", max_in_row=2)
        .add_option("apple", "Apple", "Apple 🍏")
        .add_option("banana", "Banana", "Banana 🍌", is_picked=True)
        .add_option("pear", "Pear", "Pear 🍐")
        .wait(m.ctx_api, bot.dispatch)
    )
    await m.ctx_api.edit_message_text(
        m.chat.id,
        m_id,
        text="You picked: {}".format(", ".join([c for c in picked if picked[c]])),
    )


bot.run_forever()
