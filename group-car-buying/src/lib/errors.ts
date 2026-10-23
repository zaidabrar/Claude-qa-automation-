/** An error whose message is safe to show the user, with the HTTP status the API should return. */
export class AppError extends Error {
  constructor(message: string, public status = 400) {
    super(message);
  }
}
