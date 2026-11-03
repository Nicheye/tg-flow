import pytest

from bot.parser import message_handler
from models import Chat, ChatMessage, MentionedMessage, UserChatSubscription


@pytest.mark.asyncio
async def test_ignores_update_without_effective_message(db, make_update, mock_context):
    update = make_update("ignored")
    update.effective_message = None

    await message_handler(update, mock_context)

    assert await ChatMessage.all().count() == 0


@pytest.mark.asyncio
async def test_ignores_private_chat(db, make_update, mock_context):
    update = make_update("Hey @testuser", chat_type="private")
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 0
    assert await ChatMessage.all().count() == 0


@pytest.mark.asyncio
async def test_ignores_no_entities(db, make_update, mock_context):
    update = make_update("Just a message without mentions")
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 0
    assert await ChatMessage.all().count() == 0


@pytest.mark.asyncio
async def test_ignores_no_subscription(db, chat, make_update, mock_context):
    update = make_update("Hey @unknownuser", mentions=[(4, 12, "mention")])
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 0
    assert await ChatMessage.all().count() == 0


@pytest.mark.asyncio
async def test_ignores_username_entity_without_text(db, subscription, make_update, mock_context):
    update = make_update("x", mentions=[(0, 1, "mention")])
    update.message.text = None
    update.effective_message.text = None
    update.message.caption = None
    update.effective_message.caption = None

    await message_handler(update, mock_context)

    assert await ChatMessage.all().count() == 1
    assert await MentionedMessage.all().count() == 0


@pytest.mark.asyncio
async def test_ignores_non_mention_entities(db, subscription, make_update, mock_context):
    update = make_update("https://example.com", mentions=[(0, 19, "url")])

    await message_handler(update, mock_context)

    assert await ChatMessage.all().count() == 1
    assert await MentionedMessage.all().count() == 0


@pytest.mark.asyncio
async def test_saves_mention(db, subscription, make_update, mock_context):
    update = make_update("Hey @testuser check this", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)

    mentions = await MentionedMessage.all()
    assert len(mentions) == 1
    assert mentions[0].user_id == subscription.user_id
    assert mentions[0].text == "Hey @testuser check this"
    assert mentions[0].message_id == 12345
    mention_message = await mentions[0].chat_message
    assert mention_message.message_id == 12345


@pytest.mark.asyncio
async def test_case_insensitive_match(db, subscription, make_update, mock_context):
    """@TestUser should match subscription with tg_username='testuser'"""
    update = make_update("Hey @TestUser check this", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 1
    assert await ChatMessage.all().count() == 1


@pytest.mark.asyncio
async def test_multiple_mentions(db, make_update, mock_context):
    chat = await Chat.create(id=-100123, chat_type="supergroup", title="Test")
    await UserChatSubscription.create(user_id=1, chat=chat, tg_user_id=111, tg_username="user1")
    await UserChatSubscription.create(user_id=2, chat=chat, tg_user_id=222, tg_username="user2")

    update = make_update(
        "Hey @user1 and @user2!", chat_id=-100123, mentions=[(4, 6, "mention"), (15, 6, "mention")]
    )
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 2
    assert await ChatMessage.all().count() == 1


@pytest.mark.asyncio
async def test_text_mention_by_user_id(db, make_update, mock_context):
    """A text_mention matches the Telegram user ID even when there is no username."""
    chat = await Chat.create(id=-100123, chat_type="supergroup", title="Test")
    await UserChatSubscription.create(user_id=1, chat=chat, tg_user_id=999999, tg_username=None)

    update = make_update("Hey John!", chat_id=-100123, mentions=[(4, 4, "text_mention")])
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 1
    assert await ChatMessage.all().count() == 1


@pytest.mark.asyncio
async def test_mention_stores_correct_data(db, subscription, make_update, mock_context):
    update = make_update(
        "Important: @testuser please review",
        mentions=[(11, 9, "mention")],
        from_user_id=555,
        from_username="boss",
    )
    await message_handler(update, mock_context)

    mention = await MentionedMessage.first()
    assert mention.user_id == subscription.user_id
    assert mention.chat_id == subscription.chat_id
    assert mention.from_user_id == 555
    assert mention.from_username == "boss"
    assert mention.text == "Important: @testuser please review"
    assert mention.message_id == 12345
    mention_message = await mention.chat_message
    assert mention_message.from_username == "boss"


@pytest.mark.asyncio
async def test_updates_edited_message(db, subscription, make_update, mock_context):
    update = make_update("Original")
    await message_handler(update, mock_context)

    update.message.text = "Edited"
    update.effective_message.text = "Edited"
    await message_handler(update, mock_context)

    messages = await ChatMessage.all()
    assert len(messages) == 1
    assert messages[0].text == "Edited"


@pytest.mark.asyncio
async def test_edited_mention_updates_without_creating_duplicate(
    db, subscription, make_update, mock_context
):
    update = make_update("Hey @testuser", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)

    update.message.text = "Edited @testuser"
    update.effective_message.text = "Edited @testuser"
    update.message.entities[0].offset = 7
    await message_handler(update, mock_context)

    mentions = await MentionedMessage.all()
    assert len(mentions) == 1
    assert mentions[0].text == "Edited @testuser"


@pytest.mark.asyncio
async def test_edit_removing_mention_removes_inbox_item(
    db, subscription, make_update, mock_context
):
    update = make_update("Hey @testuser", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)

    update.message.text = "No mention now"
    update.effective_message.text = "No mention now"
    update.message.entities = None
    update.effective_message.entities = None
    update.message.caption_entities = None
    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 0


@pytest.mark.asyncio
async def test_repeated_same_username_creates_one_mention(
    db, subscription, make_update, mock_context
):
    update = make_update(
        "@testuser and @testuser",
        mentions=[(0, 9, "mention"), (14, 9, "mention")],
    )

    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 1


@pytest.mark.asyncio
async def test_edit_retargets_mention_to_another_subscription(
    db, chat, subscription, make_update, mock_context
):
    other = await UserChatSubscription.create(
        user_id=2,
        chat=chat,
        tg_user_id=222,
        tg_username="other",
    )
    update = make_update("Hey @testuser", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)

    update.message.text = "Hey @other"
    update.effective_message.text = "Hey @other"
    update.message.entities[0].length = 6
    await message_handler(update, mock_context)

    mentions = await MentionedMessage.all()
    assert len(mentions) == 1
    assert mentions[0].subscription_id == other.id
    assert mentions[0].text == "Hey @other"


@pytest.mark.asyncio
async def test_repairs_duplicate_mentions_for_same_subscription(
    db, subscription, make_update, mock_context
):
    update = make_update("Hey @testuser", mentions=[(4, 9, "mention")])
    await message_handler(update, mock_context)
    message = await ChatMessage.get()
    await MentionedMessage.create(
        user_id=subscription.user_id,
        chat_id=subscription.chat_id,
        subscription_id=subscription.id,
        chat_message=message,
        message_id=message.message_id,
        from_user_id=message.from_user_id,
        from_username=message.from_username,
        text=message.text or "",
        message_date=message.message_date,
    )

    await message_handler(update, mock_context)

    assert await MentionedMessage.all().count() == 1


@pytest.mark.asyncio
async def test_saves_caption_message_for_full_feed(db, subscription, make_update, mock_context):
    update = make_update("")
    update.message.text = None
    update.effective_message.text = None
    update.message.caption = "Photo caption"
    update.effective_message.caption = "Photo caption"
    update.message.entities = None
    update.message.caption_entities = None

    await message_handler(update, mock_context)

    message = await ChatMessage.get()
    assert message.text == "Photo caption"


@pytest.mark.asyncio
async def test_ignores_message_without_sender(db, make_update, mock_context):
    update = make_update("System message")
    update.message.from_user = None
    update.effective_message.from_user = None
    update.message.sender_chat = None
    update.effective_message.sender_chat = None

    await message_handler(update, mock_context)

    assert await ChatMessage.all().count() == 0
