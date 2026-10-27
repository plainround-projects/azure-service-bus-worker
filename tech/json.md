# JSON

*The format of the command messages, the replay tool's repairs and the log lines. Pinned here: JSON (RFC 8259).*

## What it is

JSON is a text format for structured data. It has objects (`{"key": value}`), arrays (`[1, 2]`), strings, numbers, `true`, `false` and `null`. Almost every programming language and web service can read and write it.

## Why this repository uses it

Every order command is a JSON document in a Service Bus message body, and every log line is a JSON object.

## Where it appears

| File | What it does with it |
|---|---|
| `src/order_worker/domain/commands.py` | Parses and writes command bodies. |
| `src/order_worker/domain/repair.py` | Fixes a poison command's amount. |
| `src/order_worker/infrastructure/logging.py` | One JSON object per log line. |

## How it works underneath

A JSON document is a tree. An object maps names to values; an array is an ordered list. A reader parses the text into the language's own maps and lists, and a writer does the reverse. JSON has no comments and no trailing commas, and all keys are strings.

Programs that log JSON print one object per line, so a log system can read each line as a record. Azure Policy definitions are JSON documents: the rule is a nested tree of conditions.

## Walkthrough of this repository's use

```python
    def to_json(self) -> str:
        """Render the command the way the producer sends it: the amount as a decimal number of currency units."""
        return json.dumps(
            {
                "orderId": self.order_id,
                "customerId": self.customer_id,
                "seq": self.seq,
                "amount": float(Decimal(self.amount_cents) / 100),
            }
        )
```

`json.dumps({...})` writes a dictionary as JSON text. The keys (`orderId`, `customerId`, `seq`, `amount`) are the message contract between the producer and the worker.

```python
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise InvalidCommandError("NoKnownRepair", "body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidCommandError("NoKnownRepair", "body is not a JSON object")
    payload["amount"] = DEFAULT_AMOUNT
    return json.dumps(payload)
```

`json.loads` parses the text back into a dictionary. The repair replaces one value (`payload["amount"] = DEFAULT_AMOUNT`) and writes the JSON out again, keeping every other field so the `orderId` (the idempotency key) is unchanged.

```python
POISON_BODY = json.dumps({"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": "abc"})
```

The poison command is valid JSON with an invalid value: `"amount": "abc"` is a string where a number is required. That is why it can be parsed but never accepted.

## Try it yourself

Repair the poison command.

```bash
.venv/bin/python -c "from order_worker.domain.repair import repair_body
from order_worker.domain.commands import POISON_BODY
print(POISON_BODY)
print(repair_body(POISON_BODY, 'InvalidAmount'))"
```

You should see something like this:

```text
{"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": "abc"}
{"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": 10.0}
```

See how Python values become JSON.

```bash
.venv/bin/python -c "import json; print(json.dumps({'a': 1, 'b': [True, None]}))"
```

You should see something like this:

```text
{"a": 1, "b": [true, null]}
```

## Mistakes people make

- Trailing commas and comments, which JSON does not allow.
- Using single quotes. Strings use double quotes.
- Putting a large number in JSON and losing precision in a reader that uses floating point.
- Parsing untrusted JSON into code. Only data is read here; nothing is executed.
- Forgetting that key order is not meaningful.

## Check yourself

1. **What are JSON's two container types?**
   Answer: Objects (names to values) and arrays (ordered lists).

2. **Can JSON have comments?**
   Answer: No.

3. **Why do loggers print one JSON object per line?**
   Answer: So a log system can treat each line as one record.

4. **What quote marks does JSON use?**
   Answer: Double quotes only.

5. **What is the value `null`?**
   Answer: The explicit absence of a value.

## Further reading

- JSON: https://www.json.org/json-en.html
- RFC 8259: https://www.rfc-editor.org/rfc/rfc8259
